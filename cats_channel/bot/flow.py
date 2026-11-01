"""Private entry-state transitions, serialized without blocking media work."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import TelegramObject

from .entry import EntryContractError, internal_id
from .lifecycle import complete_cleanup


class PrivateEntryStates(StatesGroup):
    reply_entry = State()


async def _clear_preserving_primary(state: FSMContext, primary: BaseException) -> None:
    """Clear partial state without replacing the failure that required cleanup."""
    try:
        await complete_cleanup(state.clear())
    except asyncio.CancelledError as cleanup_cancellation:
        if isinstance(primary, asyncio.CancelledError):
            raise primary from cleanup_cancellation.__cause__
        raise cleanup_cancellation from primary
    except BaseException as cleanup_error:
        raise primary from cleanup_error
    raise primary


@dataclass(frozen=True)
class PrivateEntryContext:
    thread_id: str | None = None
    parent_post_id: str | None = None
    submission_id: str | None = None

    def __post_init__(self) -> None:
        if self.thread_id is not None:
            internal_id(self.thread_id)
        if self.parent_post_id is not None:
            internal_id(self.parent_post_id)
        if self.parent_post_id is not None and self.thread_id is None:
            raise EntryContractError()
        if self.submission_id is not None:
            internal_id(self.submission_id)

    def to_data(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value is not None}


async def read_private_entry(state: FSMContext) -> PrivateEntryContext | None:
    if await state.get_state() != PrivateEntryStates.reply_entry.state:
        return None
    try:
        return PrivateEntryContext(**await state.get_data())
    except (TypeError, EntryContractError):
        await _clear_preserving_primary(state, EntryContractError())


@dataclass
class _Transition:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    version: int = 0
    users: int = 0
    entry: asyncio.Future | None = None
    media_claimed: bool = False


@dataclass
class FlowLease:
    state: FSMContext
    transition: _Transition
    version: int

    async def begin_entry(self) -> None:
        async with self.transition.lock:
            if self.version == self.transition.version:
                self.transition.entry = asyncio.get_running_loop().create_future()

    async def finish_entry(self) -> None:
        async with self.transition.lock:
            pending = self.transition.entry
            if (
                self.version == self.transition.version
                and pending is not None
                and not pending.done()
            ):
                pending.set_result(None)

    async def admit_video(self) -> PrivateEntryContext | None:
        async with self.transition.lock:
            if self.version != self.transition.version or self.transition.media_claimed:
                return None
            self.transition.media_claimed = True
            pending = self.transition.entry
            if pending is None:
                return await read_private_entry(self.state)
        try:
            context = await asyncio.wait_for(asyncio.shield(pending), 30)
        except TimeoutError:
            return None
        return context if await self.is_current() else None

    async def select(
        self,
        context: PrivateEntryContext,
        notify: Callable[[], Awaitable[Any]],
        *,
        invalidate_previous: bool = False,
    ) -> bool:
        async with self.transition.lock:
            if self.version != self.transition.version:
                return False  # A newer recognized command replaced this entry.
            if invalidate_previous:
                self.transition.version += 1
                self.version = self.transition.version
                # A previous generation's acquisition cannot claim this selection.
                self.transition.media_claimed = False
            try:
                await self.state.set_data(context.to_data())
                await self.state.set_state(PrivateEntryStates.reply_entry)
                await notify()
                pending = self.transition.entry
                if pending is not None and not pending.done():
                    pending.set_result(context)
            except BaseException as error:  # noqa: BLE001 - cancellation also clears partial state
                await _clear_preserving_primary(self.state, error)
            return True

    async def is_current(self) -> bool:
        async with self.transition.lock:
            return self.version == self.transition.version

    @asynccontextmanager
    async def commit_guard(self) -> AsyncIterator[bool]:
        """Order durable intake against replacement; never hold during acquisition."""
        async with self.transition.lock:
            yield self.version == self.transition.version

    async def clear(self) -> bool:
        async with self.transition.lock:
            if self.version != self.transition.version:
                return False
            await complete_cleanup(self.state.clear())
            return True


class PrivateFlowCoordinator:
    def __init__(self) -> None:
        self._transitions: dict[StorageKey, _Transition] = {}

    @asynccontextmanager
    async def replace(self, state: FSMContext) -> AsyncIterator[FlowLease]:
        transition = self._transitions.setdefault(state.key, _Transition())
        transition.users += 1
        try:
            async with transition.lock:
                if transition.entry is not None and not transition.entry.done():
                    transition.entry.set_result(None)
                transition.entry = None
                transition.media_claimed = False
                transition.version += 1
                await complete_cleanup(state.clear())
                lease = FlowLease(state, transition, transition.version)
            yield lease
        finally:
            transition.users -= 1
            if not transition.users:
                self._transitions.pop(state.key, None)

    @asynccontextmanager
    async def continue_current(
        self, state: FSMContext, *, captured: FlowLease | None = None
    ) -> AsyncIterator[FlowLease]:
        transition = self._transitions.setdefault(state.key, _Transition())
        transition.users += 1
        try:
            async with transition.lock:
                lease = captured or FlowLease(state, transition, transition.version)
            yield lease
        finally:
            transition.users -= 1
            if not transition.users:
                self._transitions.pop(state.key, None)

    @property
    def pending_count(self) -> int:
        return len(self._transitions)


class PrivateFlowMiddleware(BaseMiddleware):
    """Inner middleware: authorization and command filters have already passed."""

    def __init__(self, coordinator: PrivateFlowCoordinator) -> None:
        self._coordinator = coordinator

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        text = getattr(event, "text", None)
        command = text.split(maxsplit=1)[0] if isinstance(text, str) else ""
        if not command.startswith("/"):
            return await handler(event, data)
        if "@" in command:
            mention = command.rsplit("@", 1)[1]
            me = await data["bot"].me()
            if me.username is None or mention.casefold() != me.username.casefold():
                return await handler(event, data)
        async with self._coordinator.replace(data["state"]) as lease:
            data["flow_lease"] = lease
            return await handler(event, data)


class VideoArrivalMiddleware(BaseMiddleware):
    """Capture the arrival generation before asynchronous router filters run."""

    def __init__(self, coordinator: PrivateFlowCoordinator) -> None:
        self.coordinator = coordinator

    async def __call__(self, handler, event, data):
        if getattr(event, "video", None) is None:
            return await handler(event, data)
        async with self.coordinator.continue_current(data["state"]) as lease:
            data["video_lease"] = lease
            return await handler(event, data)
