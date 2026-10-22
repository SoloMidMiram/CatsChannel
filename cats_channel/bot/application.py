"""Testable aiogram composition root and polling lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage

from ..config import Settings
from ..diagnostics import configure_logging, log_failure
from ..intake import SubmissionIntakeService
from ..services.media_service import MediaService
from ..submissions import LibraryManifestSourceResolver
from .context import BotOperationRegistry, OperationLoggingMiddleware
from .dispatcher import ApplicationDispatcher
from .entry import ReplyTargetResolver, UnavailableReplyTargetResolver
from .errors import diagnostic_error
from .flow import PrivateFlowCoordinator, PrivateFlowMiddleware
from .handlers import create_admin_router
from .lifecycle import complete_cleanup
from .telegram_media import TelegramMediaAdapter
from .transport import create_configured_bot

ResourceFactory = Callable[[], AbstractAsyncContextManager[Any]]

if TYPE_CHECKING:
    from ..persistence.contracts import PersistenceUnitOfWork


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
    intake_service: SubmissionIntakeService | None
    telegram_media_adapter: TelegramMediaAdapter
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
        primary: BaseException | None = None
        cleanup_errors: list[Exception] = []
        cleanup_cancellation: asyncio.CancelledError | None = None

        def record_cleanup(error: Exception) -> None:
            if error is not primary and all(existing is not error for existing in cleanup_errors):
                cleanup_errors.append(error)
                self._log_lifecycle_failure(error)

        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            primary = error
            try:
                await complete_cleanup(self._stop_owned(task))
            except asyncio.CancelledError as repeated_cancellation:
                if isinstance(repeated_cancellation.__cause__, Exception):
                    record_cleanup(repeated_cancellation.__cause__)
            except Exception as stop_error:  # noqa: BLE001 - owned boundary records cleanup
                record_cleanup(stop_error)
        except BaseException as error:  # noqa: BLE001 - cleanup must run for every exit
            primary = error

        try:
            await complete_cleanup(self._close(stack, polling_bot))
        except asyncio.CancelledError as error:
            cleanup_cancellation = error
            if isinstance(error.__cause__, Exception):
                record_cleanup(error.__cause__)
        except Exception as error:  # noqa: BLE001 - owned boundary records cleanup
            record_cleanup(error)

        if isinstance(primary, asyncio.CancelledError):
            if cleanup_errors:
                raise primary from cleanup_errors[0]
            raise primary
        if cleanup_cancellation is not None:
            if primary is not None:
                raise cleanup_cancellation from primary
            raise cleanup_cancellation
        if primary is not None:
            if isinstance(primary, Exception):
                self._log_lifecycle_failure(primary)
            if cleanup_errors:
                raise primary from cleanup_errors[0]
            raise primary
        if cleanup_errors:
            raise cleanup_errors[0]

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
    persistence_unit_of_work: Callable[[], PersistenceUnitOfWork] | None = None,
    intake_service: SubmissionIntakeService | None = None,
    telegram_media_adapter: TelegramMediaAdapter | None = None,
    resources: tuple[ResourceFactory, ...] = (),
) -> BotApplication:
    """Compose the bot without network access or import-time resource creation."""
    settings.require_bot()
    app_logger = logger or configure_logging(settings.log_level)
    service = media_service or MediaService(settings)
    media_gate = asyncio.Lock()
    operation_registry = BotOperationRegistry()
    flow_coordinator = PrivateFlowCoordinator()
    if persistence_unit_of_work is not None:
        if reply_target_resolver is not None:
            raise ValueError("Configure one reply resolver owner")
        from ..reply_chains.resolver import DatabaseReplyTargetResolver
        from ..reply_chains.service import ReplyChainService

        try:
            destination = int(settings.channel_id or "")
        except ValueError:
            raise ValueError("Persistent reply entries require numeric CHANNEL_ID") from None

        async def authorize_actor(actor_id, target):
            return actor_id == settings.admin_user_id

        reply_chains = ReplyChainService(persistence_unit_of_work, destination_chat_id=destination)
        reply_target_resolver = DatabaseReplyTargetResolver(
            reply_chains,
            authorize_actor=authorize_actor,
        )
        if intake_service is None:
            intake_service = SubmissionIntakeService(
                persistence_unit_of_work,
                LibraryManifestSourceResolver(),
                reply_chains=reply_chains,
            )
    publication_service = None
    owned_bot = bot if bot is not None else create_configured_bot(settings)
    if persistence_unit_of_work is not None:
        from ..adapters.aiogram_publisher import AiogramPublisher
        from ..publication.service import PublicationService

        publication_service = PublicationService(
            persistence_unit_of_work,
            reply_chains=reply_chains,
            transport=AiogramPublisher(owned_bot, settings, destination_chat_id=destination),
            destination_chat_id=destination,
            logger=app_logger,
        )
    adapter = telegram_media_adapter or TelegramMediaAdapter(settings)
    dispatcher = ApplicationDispatcher(
        storage=storage,
        settings=settings,
        media_service=service,
        media_gate=media_gate,
        logger=app_logger,
        reply_target_resolver=reply_target_resolver or UnavailableReplyTargetResolver(),
        intake_service=intake_service,
        publication_service=publication_service,
        telegram_media_adapter=adapter,
        flow_coordinator=flow_coordinator,
    )
    if publication_service is not None:
        dispatcher.startup.register(publication_service.recover_abandoned)
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
    router.callback_query.outer_middleware(
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
        bot=owned_bot,
        flow_coordinator=flow_coordinator,
        intake_service=intake_service,
        telegram_media_adapter=adapter,
        resources=resources,
    )


async def run_bot(settings: Settings) -> None:
    """Create owned resources and run polling until shutdown."""
    if not settings.reply_entries_enabled:
        application = create_bot_application(settings)
        await application.start_polling()
        return
    from ..persistence import Database

    database = Database.from_settings(settings)

    @asynccontextmanager
    async def owned_database():
        try:
            yield database
        finally:
            await database.dispose()

    try:
        application = create_bot_application(
            settings, persistence_unit_of_work=database.unit_of_work, resources=(owned_database,)
        )
    except BaseException as primary:
        try:
            await complete_cleanup(database.dispose())
        except asyncio.CancelledError as cleanup_cancellation:
            if isinstance(primary, asyncio.CancelledError):
                raise primary from cleanup_cancellation.__cause__
            raise cleanup_cancellation from primary
        except Exception as cleanup_error:
            raise primary from cleanup_error
        raise
    await application.start_polling()
