"""Testable aiogram composition root and polling lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from ..config import Settings
from ..diagnostics import configure_logging
from ..services.media_service import MediaService
from .context import BotOperationRegistry, OperationLoggingMiddleware
from .handlers import create_admin_router


@dataclass(frozen=True)
class BotApplication:
    """Owned dependencies and dispatcher for one bot process."""

    settings: Settings
    dispatcher: Dispatcher
    media_service: MediaService
    media_gate: asyncio.Lock
    operation_registry: BotOperationRegistry
    logger: logging.Logger

    async def start_polling(self, bot: Bot) -> None:
        await self.dispatcher.start_polling(bot)


def create_bot_application(
    settings: Settings,
    *,
    media_service: MediaService | None = None,
    logger: logging.Logger | None = None,
    clock: Callable[[], float] = time.monotonic,
    correlation_id_factory: Callable[[], str] | None = None,
) -> BotApplication:
    """Compose the bot without network access or import-time resource creation."""
    settings.require_bot()
    app_logger = logger or configure_logging(settings.log_level)
    service = media_service or MediaService(settings)
    media_gate = asyncio.Lock()
    operation_registry = BotOperationRegistry()
    dispatcher = Dispatcher(
        settings=settings,
        media_service=service,
        media_gate=media_gate,
        logger=app_logger,
    )
    router = create_admin_router(settings, operation_registry)
    router.message.outer_middleware(
        OperationLoggingMiddleware(
            app_logger,
            registry=operation_registry,
            clock=clock,
            correlation_id_factory=correlation_id_factory,
        )
    )
    dispatcher.include_router(router)
    return BotApplication(
        settings=settings,
        dispatcher=dispatcher,
        media_service=service,
        media_gate=media_gate,
        operation_registry=operation_registry,
        logger=app_logger,
    )


async def run_bot(settings: Settings) -> None:
    """Create owned resources and run polling until shutdown."""
    application = create_bot_application(settings)
    async with Bot(settings.bot_token.get_secret_value()) as bot:
        await application.start_polling(bot)
