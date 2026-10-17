import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import ErrorEvent, FSInputFile, Message

from .config import Settings
from .diagnostics import configure_logging, log_failure
from .errors import MediaError, error_record
from .media import youtube_url
from .services.media_service import MediaService


async def send_acquired_video(message: Message, service: MediaService, url: str) -> None:
    """Upload only a library item that completed the shared acquisition service."""
    item = await service.acquire_async(url)
    if item.media_path.suffix == ".mp4":
        await message.answer_video(FSInputFile(item.media_path), caption=url)
    else:
        await message.answer_document(FSInputFile(item.media_path), caption=url)


async def contain_unexpected_bot_error(event: ErrorEvent, logger: logging.Logger) -> bool:
    """Stop unexpected handler failures at a secret-safe router boundary."""
    error = event.exception
    if isinstance(error, asyncio.CancelledError):
        raise error
    diagnostic = MediaError(
        code="internal_error",
        log_analysis={
            "phase": "bot_update",
            "exception_types": [type(error).__name__],
            "raw_log_included": False,
        },
    )
    log_failure(logger, "bot_unexpected_failure", diagnostic, operation="bot_update")
    message = event.update.message
    if message is not None:
        try:
            record = error_record("internal_error")
            await message.answer(f"{record['message']}\n{record['action']}")
        except asyncio.CancelledError:
            raise
        except Exception as notification_error:  # noqa: BLE001 - final safe boundary
            notification = MediaError(
                code="internal_error",
                log_analysis={
                    "phase": "bot_error_notification",
                    "exception_types": [type(notification_error).__name__],
                    "raw_log_included": False,
                },
            )
            log_failure(
                logger,
                "bot_error_notification_failure",
                notification,
                operation="bot_update",
            )
    return True


async def run_bot(settings: Settings) -> None:
    settings.require_bot()
    logger = configure_logging(settings.log_level)
    router = Router()
    router.message.filter(F.chat.type == "private", F.from_user.id == settings.admin_user_id)
    busy = asyncio.Lock()
    media_service = MediaService(settings)

    @router.errors()
    async def unexpected_error(event: ErrorEvent) -> bool:
        return await contain_unexpected_bot_error(event, logger)

    @router.message(Command("start", "help"))
    async def help_message(message: Message) -> None:
        await message.answer(
            "/probe URL — metadata only\n/download URL — fetch one short video "
            "to this chat\n/publish — reply to a Telegram video to copy it "
            "to CHANNEL_ID. Nothing is published automatically."
        )

    @router.message(Command("probe", "download"))
    async def youtube(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Supply one YouTube video URL after the command.")
            return
        try:
            url = youtube_url(parts[1].strip())
        except ValueError as error:
            await message.answer(str(error))
            return
        if busy.locked():
            await message.answer("A YouTube task is already running. Try again after it finishes.")
            return
        async with busy:
            await message.answer("Working; this can take a few minutes.")
            try:
                if parts[0].split("@")[0] == "/probe":
                    info = await media_service.probe_async(url)
                    await message.answer(
                        f"{info['title']}\nDuration: {info['duration']}s\n"
                        f"Availability: {info['availability']}\n"
                        f"Live status: {info['live_status']}"
                    )
                else:
                    await send_acquired_video(message, media_service, url)
            except MediaError as error:
                log_failure(logger, "bot_media_failure", error, operation="media_command")
                record = error_record(error.code)
                await message.answer(f"{record['message']}\n{record['action']}")
            except OSError as error:
                log_failure(logger, "bot_media_failure", error, operation="media_command")
                await message.answer(
                    "A local media file operation failed. Check storage and permissions."
                )
            except TelegramAPIError as error:
                log_failure(logger, "bot_upload_failure", error, operation="media_command")
                await message.answer(
                    "Telegram could not upload the file. Check connectivity and upload limits."
                )

    @router.message(Command("publish"))
    async def publish(message: Message, bot: Bot) -> None:
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
        except TelegramAPIError as error:
            log_failure(logger, "bot_publish_failure", error, operation="publish")
            await message.answer("Publish failed. Check channel ID and bot posting permissions.")
            return
        await message.answer("Published to the configured channel.")

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    async with Bot(settings.bot_token.get_secret_value()) as bot:
        await dispatcher.start_polling(bot)
