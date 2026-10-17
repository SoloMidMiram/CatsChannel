"""Testable aiogram composition root and polling lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage

from ..config import Settings
from ..diagnostics import configure_logging, log_failure
from ..services.media_service import MediaService
from .context import BotOperationRegistry, OperationLoggingMiddleware
from .dispatcher import ApplicationDispatcher
from .entry import ReplyTargetResolver, UnavailableReplyTargetResolver
from .errors import diagnostic_error
from .flow import PrivateFlowCoordinator, PrivateFlowMiddleware
from .handlers import create_admin_router
from .lifecycle import complete_cleanup

ResourceFactory = Callable[[], AbstractAsyncContextManager[Any]]


@dataclass
class BotApplication:
    """Owned dependencies and dispatcher for one bot process."""

    settings: Settings
    dispatcher: ApplicationDispatcher
    media_service: MediaService
    media_gate: asyncio.Lock
    operation_registry: BotOperationRegistry
    logger: logging.Logger
    bot: Bot
    flow_coordinator: PrivateFlowCoordinator
    resources: tuple[ResourceFactory, ...] = ()
    _started: bool = field(default=False, init=False)

    async def _close(self, stack: AsyncExitStack, bot: Bot) -> None:
        try:
            await self.dispatcher.emit_shutdown(
                bot=bot,
                dispatcher=self.dispatcher,
                bots=(bot,),
                **self.dispatcher.workflow_data,
            )
        finally:
            await stack.aclose()

    async def _run_owned(self, stack: AsyncExitStack, bot: Bot) -> None:
        for factory in self.resources:
            await stack.enter_async_context(factory())
        await self.dispatcher.start_polling(bot, close_bot_session=False)

    async def _stop_owned(self, task: asyncio.Task) -> None:
        if not self.dispatcher.startup_completed:
            # aiogram has not created its polling tasks yet. Cancel startup and
            # let our owned finally release partially acquired resources.
            task.cancel()
        else:
            # Use the public graceful-stop API: cancelling start_polling while
            # it is in asyncio.wait can otherwise strand aiogram polling tasks.
            stop = asyncio.create_task(self.dispatcher.stop_polling())
            try:
                await asyncio.wait((task, stop), return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not stop.done():
                    stop.cancel()
                await asyncio.gather(stop, return_exceptions=True)
        await task

    async def start_polling(self, bot: Bot | None = None) -> None:
        """Run once; an optional legacy polling bot is borrowed, not closed here."""
        if self._started:
            raise RuntimeError("Bot application has already been started")
        self._started = True
        stack = AsyncExitStack()
        stack.push_async_callback(self.bot.session.close)
        polling_bot = self.bot if bot is None else bot
        task = asyncio.create_task(self._run_owned(stack, polling_bot))
        cancelled = False
        try:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
                try:
                    await complete_cleanup(self._stop_owned(task))
                except asyncio.CancelledError:
                    pass
                except Exception as error:  # noqa: BLE001 - preserve cancellation after diagnostics
                    self._log_lifecycle_failure(error)
                raise
            finally:
                try:
                    await complete_cleanup(self._close(stack, polling_bot))
                except Exception as error:
                    if not cancelled:
                        raise
                    self._log_lifecycle_failure(error)
        except asyncio.CancelledError as error:
            if isinstance(error.__cause__, Exception):
                self._log_lifecycle_failure(error.__cause__)
            raise
        except Exception as error:
            self._log_lifecycle_failure(error)
            raise

    def _log_lifecycle_failure(self, error: BaseException) -> None:
        log_failure(
            self.logger,
            "bot_lifecycle_failure",
            diagnostic_error(error, code="internal_error", phase="bot_lifecycle"),
            operation="bot_lifecycle",
        )


def create_bot_application(
    settings: Settings,
    *,
    media_service: MediaService | None = None,
    logger: logging.Logger | None = None,
    clock: Callable[[], float] = time.monotonic,
    correlation_id_factory: Callable[[], str] | None = None,
    bot: Bot | None = None,
    storage: BaseStorage | None = None,
    reply_target_resolver: ReplyTargetResolver | None = None,
    resources: tuple[ResourceFactory, ...] = (),
) -> BotApplication:
    """Compose the bot without network access or import-time resource creation."""
    settings.require_bot()
    app_logger = logger or configure_logging(settings.log_level)
    service = media_service or MediaService(settings)
    media_gate = asyncio.Lock()
    operation_registry = BotOperationRegistry()
    flow_coordinator = PrivateFlowCoordinator()
    dispatcher = ApplicationDispatcher(
        storage=storage,
        settings=settings,
        media_service=service,
        media_gate=media_gate,
        logger=app_logger,
        reply_target_resolver=reply_target_resolver or UnavailableReplyTargetResolver(),
    )
    router = create_admin_router(settings, operation_registry)
    router.message.middleware(PrivateFlowMiddleware(flow_coordinator))
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
        bot=bot if bot is not None else Bot(settings.bot_token.get_secret_value()),
        flow_coordinator=flow_coordinator,
        resources=resources,
    )


async def run_bot(settings: Settings) -> None:
    """Create owned resources and run polling until shutdown."""
    application = create_bot_application(settings)
    await application.start_polling()
