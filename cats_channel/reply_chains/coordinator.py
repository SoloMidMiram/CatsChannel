"""Application-local thread serialization; optimistic database checks remain required."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class _Slot:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class ThreadCoordinator:
    def __init__(self) -> None:
        self._slots: dict[str, _Slot] = {}

    @asynccontextmanager
    async def hold(self, thread_id: str) -> AsyncIterator[None]:
        slot = self._slots.setdefault(thread_id, _Slot())
        slot.users += 1
        try:
            async with slot.lock:
                yield
        finally:
            slot.users -= 1
            if not slot.users:
                self._slots.pop(thread_id, None)

    @property
    def pending_count(self) -> int:
        return len(self._slots)
