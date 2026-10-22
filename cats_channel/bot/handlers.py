"""Admin-only aiogram handlers with injected application dependencies."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from ..config import Settings
from ..diagnostics import log_failure
from ..errors import MediaError
from ..intake import IntakeError
from ..media import youtube_url
from ..reply_chains.errors import ReplyChainError
from ..services.media_service import MediaService
from ..submissions import SubmissionError
from .context import BotOperation, BotOperationRegistry
from .errors import answer_error_safely, contain_unexpected_bot_error, diagnostic_error
from .routers import create_post_router

HELP_TEXT = (
    "/post — submit a video or YouTube URL for a pending channel post\n"
    "/probe URL — metadata only\n"
    "/download URL — fetch one short video to this chat\n"
    "/publish — reply to a Telegram video to copy it to CHANNEL_ID. "
    "Nothing is published automatically.\n"
    "/cancel — clear the active private entry."
)


async def send_acquired_video(message: Message, service: MediaService, url: str) -> None:
    """Upload only a library item that completed the shared acquisition service."""
    item = await service.acquire_async(url)
    if item.media_path.suffix == ".mp4":
        await message.answer_video(FSInputFile(item.media_path), caption=url)
    else:
        await message.answer_document(FSInputFile(item.media_path), caption=url)


def _record_failure(
    logger: logging.Logger,
    operation: BotOperation,
    event: str,
    error: BaseException,
    *,
    code: str | None = None,
    phase: str | None = None,
) -> str:
    category = code or str(getattr(error, "code", "internal_error"))
    operation.fail(category)
    diagnostic = (
        error
        if isinstance(error, MediaError)
        else diagnostic_error(error, code=category, phase=phase or operation.operation)
    )
    log_failure(
        logger,
        event,
        diagnostic,
        operation=operation.operation,
        correlation_id=operation.correlation_id,
    )
    return category


def create_admin_router(settings: Settings, operation_registry: BotOperationRegistry) -> Router:
    """Build the private, admin-only command router without creating resources."""
    router = Router(name="admin")
    router.message.filter(F.chat.type == "private", F.from_user.id == settings.admin_user_id)
    router.callback_query.filter(
        F.message.chat.type == "private", F.from_user.id == settings.admin_user_id
    )

    @router.errors()
    async def unexpected_error(
        event,
        logger: logging.Logger,
        bot_operation: BotOperation | None = None,
    ) -> bool:
        update_event = event.update.message or event.update.callback_query
        operation = bot_operation or operation_registry.take(update_event)
        error = event.exception
        if isinstance(error, (IntakeError, SubmissionError, ReplyChainError, MediaError)):
            code = str(error.code)
            operation = operation or BotOperation("unavailable", "bot_intake", 0.0)
            _record_failure(logger, operation, "bot_intake_failure", error, code=code)
            message = event.update.message or (
                event.update.callback_query.message if event.update.callback_query else None
            )
            if isinstance(message, Message):
                await answer_error_safely(
                    message,
                    code=code,
                    logger=logger,
                    operation=operation,
                    event="bot_error_notification_failure",
                )
            return True
        return await contain_unexpected_bot_error(event, logger, operation)

    @router.message(CommandStart(deep_link=False))
    async def start_message(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("help"))
    async def help_message(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("cancel"))
    async def cancel_entry(message: Message) -> None:
        await message.answer("Cancelled.")

    @router.message(Command("probe", "download"))
    async def media_command(
        message: Message,
        media_service: MediaService,
        media_gate: asyncio.Lock,
        logger: logging.Logger,
        bot_operation: BotOperation,
    ) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Supply one YouTube video URL after the command.")
            return
        try:
            url = youtube_url(parts[1].strip())
        except ValueError as error:
            code = _record_failure(
                logger,
                bot_operation,
                "bot_media_failure",
                error,
                code="invalid_url",
                phase="media_command",
            )
            await answer_error_safely(
                message,
                code=code,
                logger=logger,
                operation=bot_operation,
                event="bot_error_notification_failure",
            )
            return
        if media_gate.locked():
            bot_operation.outcome = "busy"
            await message.answer("A YouTube task is already running. Try again after it finishes.")
            return
        async with media_gate:
            await message.answer("Working; this can take a few minutes.")
            try:
                if parts[0].split("@", 1)[0] == "/probe":
                    info = await media_service.probe_async(url)
                    await message.answer(
                        f"{info['title']}\nDuration: {info['duration']}s\n"
                        f"Availability: {info['availability']}\n"
                        f"Live status: {info['live_status']}"
                    )
                else:
                    await send_acquired_video(message, media_service, url)
            except asyncio.CancelledError:
                raise
            except MediaError as error:
                code = _record_failure(logger, bot_operation, "bot_media_failure", error)
                await answer_error_safely(
                    message,
                    code=code,
                    logger=logger,
                    operation=bot_operation,
                    event="bot_error_notification_failure",
                )
            except OSError as error:
                code = _record_failure(
                    logger,
                    bot_operation,
                    "bot_media_failure",
                    error,
                    code="local_io",
                    phase="media_command",
                )
                await answer_error_safely(
                    message,
                    code=code,
                    logger=logger,
                    operation=bot_operation,
                    event="bot_error_notification_failure",
                )
            except TelegramAPIError as error:
                code = _record_failure(
                    logger,
                    bot_operation,
                    "bot_upload_failure",
                    error,
                    code="telegram_upload",
                    phase="media_upload",
                )
                await answer_error_safely(
                    message,
                    code=code,
                    logger=logger,
                    operation=bot_operation,
                    event="bot_error_notification_failure",
                )

    @router.message(Command("publish"))
    async def publish(
        message: Message,
        bot: Bot,
        logger: logging.Logger,
        bot_operation: BotOperation,
    ) -> None:
        source = message.reply_to_message
        if not settings.channel_id or not source or not source.video:
            await message.answer("Set CHANNEL_ID, then reply /publish to a video in this chat.")
            return
        target = settings.channel_id
        try:
            await bot.copy_message(
                chat_id=int(target) if target.lstrip("-").isdigit() else target,
                from_chat_id=message.chat.id,
                message_id=source.message_id,
            )
        except asyncio.CancelledError:
            raise
        except TelegramAPIError as error:
            code = _record_failure(
                logger,
                bot_operation,
                "bot_publish_failure",
                error,
                code="telegram_publish",
                phase="publish",
            )
            await answer_error_safely(
                message,
                code=code,
                logger=logger,
                operation=bot_operation,
                event="bot_error_notification_failure",
            )
            return
        await message.answer("Published to the configured channel.")

    router.include_router(create_post_router())
    return router
