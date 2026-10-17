"""Drain accepted updates before closing FSM storage or other owned resources."""

import asyncio
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Update


class ApplicationDispatcher(Dispatcher):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.startup_completed = False
        self._accepting_updates = True
        self._updates: set[asyncio.Task] = set()
        self._shutdown_task: asyncio.Task | None = None

    async def feed_update(self, bot: Bot, update: Update, **kwargs: Any) -> Any:
        if not self._accepting_updates:
            return UNHANDLED
        task = asyncio.current_task()
        self._updates.add(task)
        try:
            return await super().feed_update(bot, update, **kwargs)
        finally:
            self._updates.discard(task)

    async def emit_startup(self, *args: Any, **kwargs: Any) -> None:
        await super().emit_startup(*args, **kwargs)
        self.startup_completed = True

    async def _shutdown(self, *args: Any, **kwargs: Any) -> None:
        self._accepting_updates = False
        tasks = tuple(self._updates)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await super().emit_shutdown(*args, **kwargs)

    async def emit_shutdown(self, *args: Any, **kwargs: Any) -> None:
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._shutdown(*args, **kwargs))
        await asyncio.shield(self._shutdown_task)

    @property
    def active_update_count(self) -> int:
        return len(self._updates)
