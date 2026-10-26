"""One-destination Bot API transport. No forwarding or source captions."""

import asyncio
import hashlib
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyParameters,
)

from ..config import Settings
from ..library import _enforce_current_policy, _read_manifest
from ..persistence.entities import TelegramMessageRef
from ..publication.errors import DeliveryRejected
from ..reply_tokens import validate_reply_token


def destination_link(reference: TelegramMessageRef) -> str | None:
    """Private supergroup/channel links require membership. Never link intake chats."""
    chat = str(reference.chat_id)
    if not chat.startswith("-100") or len(chat) <= 4 or reference.message_id <= 0:
        return None
    return f"https://t.me/c/{chat[4:]}/{reference.message_id}"


class AiogramPublisher:
    def __init__(self, bot: Bot, settings: Settings, *, destination_chat_id: int):
        self.bot = bot
        self.settings = settings
        if type(destination_chat_id) is not int or destination_chat_id == 0:
            raise ValueError("Expected numeric destination")
        self.destination = destination_chat_id

    def _local_bytes(self, submission):
        media = submission.provenance.get("media", {})
        relative = media.get("library_item_path")
        # Current library owns only YouTube items. Never accept caller-supplied paths.
        if (
            not isinstance(relative, str)
            or not re.fullmatch(r"library/youtube/[A-Za-z0-9_-]{11}", relative)
            or relative.rsplit("/", 1)[1] != submission.source_media_id
        ):
            raise DeliveryRejected()
        root = self.settings.download_dir.resolve()
        folder = (root / relative).resolve()
        if not folder.is_relative_to(root):
            raise DeliveryRejected()
        if not (folder / "manifest.json").resolve().is_relative_to(folder):
            raise DeliveryRejected()
        manifest = _read_manifest(folder)
        path = (folder / manifest["file"]["name"]).resolve()
        if not path.is_relative_to(folder) or path == folder:
            raise DeliveryRejected()
        _enforce_current_policy(manifest, self.settings)
        if manifest["source"].get("video_id") != submission.source_media_id:
            raise DeliveryRejected()
        # Snapshot the actual bytes sent: no reopen between integrity check and upload.
        with path.open("rb") as stream:
            data = stream.read(self.settings.max_download_mb * 1024 * 1024 + 1)
        evidence = submission.validation_evidence
        digest = hashlib.sha256(data).hexdigest()
        if (
            len(data) > self.settings.max_download_mb * 1024 * 1024
            or not data
            or len(data) != manifest["file"].get("size_bytes")
            or digest != manifest["file"].get("sha256")
            or len(data) != evidence.get("size_bytes")
            or digest != evidence.get("sha256")
        ):
            raise DeliveryRejected()
        return BufferedInputFile(data, filename="cat" + path.suffix), path.suffix == ".mp4"

    async def send(self, submission, *, parent):
        return await self._send(submission, parent=parent)

    async def send_review(self, submission, *, caption, reply_markup):
        return await self._send(submission, parent=None, caption=caption, reply_markup=reply_markup)

    async def _send(self, submission, *, parent, caption=None, reply_markup=None):
        try:
            if (
                submission.status != "validated"
                or submission.validation_evidence.get("full_decode") is not True
            ):
                raise DeliveryRejected()
            if parent is not None and parent.chat_id != self.destination:
                raise DeliveryRejected()
            if submission.media_origin == "telegram_native":
                if submission.provenance.get("media", {}).get("adapter") != "telegram_native":
                    raise DeliveryRejected()
                native = submission.provenance.get("telegram", {})
                file_id = native.get("file_id")
                if (
                    not isinstance(file_id, str)
                    or not file_id
                    or submission.source_provider != "telegram"
                ):
                    raise DeliveryRejected()
                # getFile on this Bot is a pre-dispatch usability check, never a send.
                file = await self.bot.get_file(file_id)
                if (
                    file.file_unique_id != native.get("file_unique_id")
                    or file.file_unique_id != submission.source_media_id
                ):
                    raise DeliveryRejected()
                payload, video = file_id, True
            elif submission.media_origin == "local_library":
                payload, video = await asyncio.to_thread(self._local_bytes, submission)
            else:
                raise DeliveryRejected()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - safe application/transport boundary
            # All errors here precede the media dispatch.
            raise DeliveryRejected() from None
        reply = (
            ReplyParameters(message_id=parent.message_id, allow_sending_without_reply=False)
            if parent
            else None
        )
        try:
            extra = {"reply_markup": reply_markup} if reply_markup is not None else {}
            if video:
                message = await self.bot.send_video(
                    self.destination, payload, caption=caption, reply_parameters=reply, **extra
                )
            else:
                message = await self.bot.send_document(
                    self.destination, payload, caption=caption, reply_parameters=reply, **extra
                )
        except (TelegramBadRequest, TelegramForbiddenError):
            # Bot API rejects the operation, including a deleted exact parent.
            raise DeliveryRejected() from None
        return TelegramMessageRef(message.chat.id, message.message_id)

    async def install_markup(self, reference, *, token, child):
        if reference.chat_id != self.destination or (child and child.chat_id != self.destination):
            raise DeliveryRejected()
        validate_reply_token(token)
        me = await self.bot.get_me()
        if not me.username or not re.fullmatch(r"[A-Za-z0-9_]+", me.username):
            raise DeliveryRejected()
        rows = [
            [
                InlineKeyboardButton(
                    text="Reply with a cat",
                    url=f"https://t.me/{me.username}?start=catreply_{token}",
                )
            ]
        ]
        if child and (link := destination_link(child)):
            rows.append([InlineKeyboardButton(text="Latest confirmed reply", url=link)])
        await self.bot.edit_message_reply_markup(
            chat_id=self.destination,
            message_id=reference.message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
