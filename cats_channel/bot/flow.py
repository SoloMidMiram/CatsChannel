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
    thread_id: str
    parent_post_id: str
    submission_id: str | None = None

    def __post_init__(self) -> None:
        internal_id(self.thread_id)
        internal_id(self.parent_post_id)
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


@dataclass
class FlowLease:
    state: FSMContext
    transition: _Transition
    version: int

    async def select(
        self, context: PrivateEntryContext, notify: Callable[[], Awaitable[Any]]
    ) -> bool:
        async with self.transition.lock:
            if self.version != self.transition.version:
                return False  # A newer recognized command replaced this entry.
            try:
                await self.state.set_data(context.to_data())
                await self.state.set_state(PrivateEntryStates.reply_entry)
                await notify()
            except BaseException as error:  # noqa: BLE001 - cancellation also clears partial state
                await _clear_preserving_primary(self.state, error)
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
                transition.version += 1
                await complete_cleanup(state.clear())
                lease = FlowLease(state, transition, transition.version)
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
        async with self._coordinator.replace(data["state"]) as lease:
            data["flow_lease"] = lease
            return await handler(event, data)
