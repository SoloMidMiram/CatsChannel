import asyncio
import threading
import time
from unittest.mock import AsyncMock, patch

import pytest

from cats_channel.bot import send_acquired_video
from cats_channel.config import Settings
from cats_channel.errors import MediaError
from cats_channel.models import LibraryItem
from cats_channel.services.media_service import MediaService

VIDEO_URL = "https://youtu.be/abcdefghijk"


async def test_async_cancellation_waits_for_worker_shutdown(tmp_path):
    service = MediaService(Settings(_env_file=None, download_dir=tmp_path))
    started = threading.Event()
    stopped = threading.Event()

    def cancellable_store(_settings, _url, *, token):
        started.set()
        while not token.cancelled:
            time.sleep(0.01)
        stopped.set()
        raise MediaError(code="cancelled")

    with patch("cats_channel.services.media_service.store_download", side_effect=cancellable_store):
        task = asyncio.create_task(service.acquire_async(VIDEO_URL))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stopped.is_set()


async def test_repeated_async_cancellation_cannot_escape_worker_shutdown(tmp_path):
    service = MediaService(Settings(_env_file=None, download_dir=tmp_path))
    started = threading.Event()
    cancellation_seen = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def slow_shutdown_store(_settings, _url, *, token):
        started.set()
        while not token.cancelled:
            time.sleep(0.01)
        cancellation_seen.set()
        release.wait(timeout=2)
        stopped.set()
        raise MediaError(code="cancelled")

    with patch(
        "cats_channel.services.media_service.store_download", side_effect=slow_shutdown_store
    ):
        task = asyncio.create_task(service.acquire_async(VIDEO_URL))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        assert await asyncio.to_thread(cancellation_seen.wait, 1)
        task.cancel()
        await asyncio.sleep(0.05)
        returned_before_shutdown = task.done()
        release.set()
        assert await asyncio.to_thread(stopped.wait, 1)
        with pytest.raises(asyncio.CancelledError):
            await task

    assert not returned_before_shutdown


async def test_bot_uploads_validated_library_path(tmp_path):
    media_path = tmp_path / "library" / "youtube" / "abcdefghijk" / "media.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"video")
    item = LibraryItem(
        status="stored",
        item_path="library/youtube/abcdefghijk",
        media_path=media_path,
        manifest={"file": {"name": "media.mp4"}},
    )
    service = AsyncMock()
    service.acquire_async.return_value = item
    message = AsyncMock()

    await send_acquired_video(message, service, VIDEO_URL)

    message.answer_video.assert_awaited_once()
    message.answer_document.assert_not_awaited()


async def test_bot_never_uploads_after_acquisition_failure():
    service = AsyncMock()
    service.acquire_async.side_effect = MediaError(code="media_validation")
    message = AsyncMock()

    with pytest.raises(MediaError) as error:
        await send_acquired_video(message, service, VIDEO_URL)

    assert error.value.code == "media_validation"
    message.answer_video.assert_not_awaited()
    message.answer_document.assert_not_awaited()
