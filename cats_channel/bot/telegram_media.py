"""Download and validate Telegram-native video bytes before intake."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from aiogram import Bot
from aiogram.types import Video

from ..adapters.process import CancellationToken
from ..adapters.validation import validate_media
from ..config import Settings
from ..errors import MediaError
from ..persistence.entities import TelegramMessageRef
from ..submissions import (
    MediaValidationEvidence,
    SourceMetadata,
    SubmissionVideoMetadata,
    ValidatedTelegramMedia,
)

Validator = Callable[..., dict[str, object]]


class _BoundedWriter:
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._size = 0

    def write(self, value: bytes) -> int:
        if self._size + len(value) > self._limit:
            raise MediaError(code="policy_limit")
        written = self._stream.write(value)
        self._size += written
        return written

    def seek(self, *args: object) -> int:
        return self._stream.seek(*args)

    def tell(self) -> int:
        return self._stream.tell()

    def flush(self) -> None:
        self._stream.flush()


class TelegramMediaAdapter:
    """Own a temporary copy and require full decode before returning media."""

    def __init__(self, settings: Settings, *, validator: Validator = validate_media) -> None:
        self._settings = settings
        self._validator = validator

    async def acquire(
        self,
        bot: Bot,
        video: Video,
        reference: TelegramMessageRef,
    ) -> ValidatedTelegramMedia:
        limit = self._settings.max_download_mb * 1024 * 1024
        if video.file_size is not None and video.file_size > limit:
            raise MediaError(code="policy_limit")

        try:
            temporary = tempfile.TemporaryDirectory(prefix="cats-channel-telegram-")
        except OSError as error:
            raise MediaError(code="local_io") from error
        with temporary as folder:
            path = Path(folder) / "media.bin"
            try:
                with path.open("w+b") as destination:
                    await bot.download(
                        video,
                        destination=_BoundedWriter(destination, limit),
                        timeout=self._settings.bot_api_file_timeout_seconds,
                        seek=False,
                    )
            except asyncio.CancelledError:
                raise
            except MediaError:
                raise
            except TimeoutError as error:
                raise MediaError(code="timeout") from error
            except OSError as error:
                raise MediaError(code="local_io") from error
            except Exception as error:
                raise MediaError(code="telegram_download") from error

            try:
                size = path.stat().st_size
            except OSError as error:
                raise MediaError(code="local_io") from error
            if size <= 0 or size > limit:
                raise MediaError(code="policy_limit" if size > limit else "media_validation")

            token = CancellationToken()
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._validator,
                    path,
                    video.duration if video.duration > 0 else None,
                    max_duration_seconds=self._settings.max_duration_seconds,
                    token=token,
                )
            )
            try:
                validation = await asyncio.shield(task)
            except asyncio.CancelledError:
                token.cancel()
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:  # noqa: BLE001 - retrieve the owned result below
                        break
                try:
                    task.result()
                except (Exception, asyncio.CancelledError):  # noqa: BLE001
                    # Caller cancellation stays primary after the owned worker is drained.
                    ...
                raise

            duration = float(validation["duration_seconds"])
            audio_codecs = validation.get("audio_codecs")
            audio_codec = (
                str(audio_codecs[0]) if isinstance(audio_codecs, list) and audio_codecs else None
            )
            try:
                with path.open("rb") as media_file:
                    digest = hashlib.file_digest(media_file, "sha256").hexdigest()
            except OSError as error:
                raise MediaError(code="local_io") from error
            return ValidatedTelegramMedia(
                source_provider="telegram",
                source_media_id=video.file_unique_id,
                reference=reference,
                file_id=video.file_id,
                file_unique_id=video.file_unique_id,
                metadata=SubmissionVideoMetadata(
                    title=None,
                    duration_seconds=duration,
                    width=validation.get("width")
                    if isinstance(validation.get("width"), int)
                    else video.width,
                    height=validation.get("height")
                    if isinstance(validation.get("height"), int)
                    else video.height,
                    video_codec=(
                        str(validation["video_codec"])
                        if validation.get("video_codec") is not None
                        else None
                    ),
                    audio_codec=audio_codec,
                    container=(
                        str(validation["format_name"])
                        if validation.get("format_name") is not None
                        else None
                    ),
                ),
                validation=MediaValidationEvidence(
                    validator="ffmpeg_full_decode",
                    validated_at=datetime.now(UTC),
                    size_bytes=size,
                    duration_seconds=duration,
                    sha256=digest,
                    video_stream_count=int(validation["video_stream_count"]),
                    audio_stream_count=int(validation["audio_stream_count"]),
                    full_decode=validation.get("full_decode") == "passed",
                ),
                source_metadata=SourceMetadata(),
                provenance={"adapter": "telegram_native"},
            )
