import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.types import Video

from cats_channel.bot.telegram_media import TelegramMediaAdapter
from cats_channel.config import Settings
from cats_channel.errors import MediaError
from cats_channel.persistence import TelegramMessageRef


def settings(**updates):
    return Settings(_env_file=None, max_download_mb=1, **updates)


def video(**updates):
    values = {
        "file_id": "file-id",
        "file_unique_id": "stable-file-id",
        "width": 360,
        "height": 640,
        "duration": 10,
        "file_size": 5,
    }
    values.update(updates)
    return Video(**values)


def validation(**updates):
    values = {
        "duration_seconds": 10.0,
        "format_name": "mov,mp4",
        "video_stream_count": 1,
        "audio_stream_count": 1,
        "video_codec": "h264",
        "width": 360,
        "height": 640,
        "audio_codecs": ["aac"],
        "full_decode": "passed",
    }
    values.update(updates)
    return values


class FakeBot:
    def __init__(self, payload=b"video"):
        self.payload = payload
        self.calls = 0

    async def download(self, _video, destination, **_kwargs):
        self.calls += 1
        destination.write(self.payload)


class TimeoutBot:
    async def download(self, *_args, **_kwargs):
        raise TimeoutError


async def test_adapter_validates_actual_bytes_and_builds_truthful_media():
    bot = FakeBot()
    seen = {}

    def validate(path: Path, expected, **kwargs):
        seen.update(path=path, expected=expected, kwargs=kwargs, payload=path.read_bytes())
        return validation()

    adapter = TelegramMediaAdapter(settings(), validator=validate)
    result = await adapter.acquire(bot, video(), TelegramMessageRef(42, 7))

    assert seen["payload"] == b"video"
    assert seen["expected"] == 10
    assert result.source_provider == "telegram"
    assert result.source_media_id == "stable-file-id"
    assert result.validation.size_bytes == 5
    assert result.validation.full_decode is True
    assert result.metadata.title is None
    assert not seen["path"].exists()


async def test_adapter_rejects_declared_and_streamed_oversize_without_validation():
    validate = pytest.fail
    adapter = TelegramMediaAdapter(settings(), validator=validate)
    with pytest.raises(MediaError) as declared:
        await adapter.acquire(
            FakeBot(), video(file_size=2 * 1024 * 1024), TelegramMessageRef(42, 7)
        )
    assert declared.value.code == "policy_limit"
    with pytest.raises(MediaError) as streamed:
        await adapter.acquire(
            FakeBot(b"x" * (1024 * 1024 + 1)),
            video(file_size=None),
            TelegramMessageRef(42, 8),
        )
    assert streamed.value.code == "policy_limit"


async def test_adapter_cancellation_drains_validation_before_temp_cleanup():
    started = threading.Event()
    release = threading.Event()
    observed = SimpleNamespace(existed_after_release=False)

    def validate(path: Path, _expected, **_kwargs):
        started.set()
        release.wait(2)
        observed.existed_after_release = path.exists()
        return validation()

    adapter = TelegramMediaAdapter(settings(), validator=validate)
    task = asyncio.create_task(adapter.acquire(FakeBot(), video(), TelegramMessageRef(42, 9)))
    await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert observed.existed_after_release is True


async def test_adapter_classifies_telegram_transfer_timeout_without_validation():
    adapter = TelegramMediaAdapter(settings(), validator=pytest.fail)
    with pytest.raises(MediaError) as caught:
        await adapter.acquire(TimeoutBot(), video(), TelegramMessageRef(42, 10))
    assert caught.value.code == "timeout"
