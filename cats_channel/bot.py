import asyncio

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from .config import Settings
from .errors import MediaError
from .media import youtube_url
from .services.media_service import MediaService


async def send_acquired_video(message: Message, service: MediaService, url: str) -> None:
    """Upload only a library item that completed the shared acquisition service."""
    item = await service.acquire_async(url)
    if item.media_path.suffix == ".mp4":
        await message.answer_video(FSInputFile(item.media_path), caption=url)
    else:
        await message.answer_document(FSInputFile(item.media_path), caption=url)


async def run_bot(settings: Settings) -> None:
    settings.require_bot()
    router = Router()
    router.message.filter(F.chat.type == "private", F.from_user.id == settings.admin_user_id)
    busy = asyncio.Lock()
    media_service = MediaService(settings)

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
            except (MediaError, OSError):
                await message.answer(
                    "Could not process this video. Check access, yt-dlp version, "
                    "cookie configuration, size and duration limits. "
                    "Use the local probe for a safe diagnostic."
                )
            except TelegramAPIError:
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
        except TelegramAPIError:
            await message.answer("Publish failed. Check channel ID and bot posting permissions.")
            return
        await message.answer("Published to the configured channel.")

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    async with Bot(settings.bot_token.get_secret_value()) as bot:
        await dispatcher.start_polling(bot)
