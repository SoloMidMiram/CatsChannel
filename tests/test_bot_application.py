import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import CopyMessage, GetMe, SendDocument, SendMessage, SendVideo, TelegramMethod
from aiogram.types import Chat, Message, MessageEntity, MessageId, Update, User, Video

from cats_channel.bot import create_bot_application
from cats_channel.bot.handlers import HELP_TEXT
from cats_channel.config import Settings
from cats_channel.diagnostics import configure_logging
from cats_channel.errors import MediaError, error_record
from cats_channel.models import LibraryItem

ADMIN_ID = 42
BOT_TOKEN = "123456:TEST_TOKEN"
VIDEO_URL = "https://youtu.be/abcdefghijk"


class RecordingSession(BaseSession):
    def __init__(
        self,
        *,
        fail_when: Callable[[TelegramMethod[Any]], bool] | None = None,
    ) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self.fail_when = fail_when
        self.closed = False
        self._message_id = 1000

    async def close(self) -> None:
        self.closed = True

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.methods.append(method)
        if self.fail_when is not None and self.fail_when(method):
            raise RuntimeError("token=private phone=private third-party body")
        self._message_id += 1
        if isinstance(method, GetMe):
            return User(id=bot.id, is_bot=True, first_name="Cats", username="cats_test_bot")
        if isinstance(method, CopyMessage):
            return MessageId(message_id=self._message_id)
        return Message(
            message_id=self._message_id,
            date=datetime.now(UTC),
            chat=Chat(id=ADMIN_ID, type="private"),
            text=getattr(method, "text", None),
        )

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:  # pragma: no cover - required async-generator shape
            yield b""


def settings(**updates: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "bot_token": BOT_TOKEN,
        "admin_user_id": ADMIN_ID,
        "channel_id": "-100123456789",
        "log_level": "WARNING",
    }
    values.update(updates)
    return Settings(**values)


def update(
    text: str,
    *,
    update_id: int = 1,
    user_id: int = ADMIN_ID,
    chat_type: str = "private",
    reply_video: bool = False,
) -> Update:
    command = text.split(maxsplit=1)[0]
    reply = None
    if reply_video:
        reply = Message(
            message_id=50,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type=chat_type),
            from_user=User(id=user_id, is_bot=False, first_name="Admin"),
            video=Video(
                file_id="video-file-id",
                file_unique_id="video-unique-id",
                width=360,
                height=640,
                duration=10,
            ),
        )
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type=chat_type),
            from_user=User(id=user_id, is_bot=False, first_name="Admin"),
            text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=len(command))],
            reply_to_message=reply,
        ),
    )


def library_item(tmp_path: Path, *, suffix: str = ".mp4") -> LibraryItem:
    media_path = tmp_path / "library" / "youtube" / "abcdefghijk" / f"media{suffix}"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"validated-video")
    return LibraryItem(
        status="stored",
        item_path="library/youtube/abcdefghijk",
        media_path=media_path,
        manifest={"file": {"name": media_path.name}},
    )


def sent_texts(session: RecordingSession) -> list[str]:
    return [method.text for method in session.methods if isinstance(method, SendMessage)]


@pytest.fixture
def bot_and_session():
    session = RecordingSession()
    bot = Bot(BOT_TOKEN, session=session)
    return bot, session


async def test_factory_injects_dependencies_without_network_access():
    service = AsyncMock()
    application = create_bot_application(settings(), media_service=service)

    assert application.dispatcher.workflow_data["settings"] is application.settings
    assert application.dispatcher.workflow_data["media_service"] is service
    assert application.dispatcher.workflow_data["media_gate"] is application.media_gate
    assert application.dispatcher.workflow_data["logger"] is application.logger
    assert application.dispatcher.sub_routers[0].name == "admin"


async def test_real_dispatcher_preserves_private_admin_filter(bot_and_session):
    bot, session = bot_and_session
    application = create_bot_application(settings(), media_service=AsyncMock())

    await application.dispatcher.feed_update(bot, update("/help", update_id=1))
    await application.dispatcher.feed_update(bot, update("/start", update_id=4))
    await application.dispatcher.feed_update(bot, update("/help", update_id=2, user_id=999))
    await application.dispatcher.feed_update(bot, update("/help", update_id=3, chat_type="group"))

    assert sent_texts(session) == [HELP_TEXT, HELP_TEXT]


async def test_probe_uses_injected_service_and_preserves_metadata_response(bot_and_session):
    bot, session = bot_and_session
    service = AsyncMock()
    service.probe_async.return_value = {
        "title": "Cat Help",
        "duration": 12,
        "availability": "public",
        "live_status": "not_live",
    }
    application = create_bot_application(settings(), media_service=service)

    await application.dispatcher.feed_update(bot, update(f"/probe {VIDEO_URL}"))

    service.probe_async.assert_awaited_once_with("https://www.youtube.com/watch?v=abcdefghijk")
    assert sent_texts(session) == [
        "Working; this can take a few minutes.",
        "Cat Help\nDuration: 12s\nAvailability: public\nLive status: not_live",
    ]


async def test_download_uploads_only_media_returned_by_injected_service(bot_and_session, tmp_path):
    bot, session = bot_and_session
    item = library_item(tmp_path)
    service = AsyncMock()
    service.acquire_async.return_value = item
    application = create_bot_application(settings(), media_service=service)

    await application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}"))

    service.acquire_async.assert_awaited_once_with("https://www.youtube.com/watch?v=abcdefghijk")
    assert sent_texts(session) == ["Working; this can take a few minutes."]
    videos = [method for method in session.methods if isinstance(method, SendVideo)]
    assert len(videos) == 1
    assert Path(videos[0].video.path) == item.media_path
    assert not any(isinstance(method, SendDocument) for method in session.methods)


async def test_acquisition_failure_reuses_policy_and_never_uploads(bot_and_session, capsys):
    bot, session = bot_and_session
    service = AsyncMock()
    service.acquire_async.side_effect = MediaError(code="media_validation")
    application = create_bot_application(
        settings(),
        media_service=service,
        logger=configure_logging("INFO"),
        correlation_id_factory=lambda: "mediafail1",
    )

    await application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}"))

    assert not any(isinstance(method, (SendVideo, SendDocument)) for method in session.methods)
    assert any("failed local playback validation" in text for text in sent_texts(session))
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    failure = next(record for record in records if record["event"] == "bot_media_failure")
    completion = next(record for record in records if record["event"] == "bot_operation_finished")
    assert failure["code"] == "media_validation"
    assert failure["correlation_id"] == "mediafail1"
    assert completion["outcome"] == "error"
    assert completion["error_category"] == "media_validation"


async def test_real_dispatcher_enforces_one_active_media_task(bot_and_session, tmp_path):
    bot, session = bot_and_session
    started = asyncio.Event()
    release = asyncio.Event()
    item = library_item(tmp_path)

    class BlockingService:
        async def acquire_async(self, url: str) -> LibraryItem:
            started.set()
            await release.wait()
            return item

    application = create_bot_application(settings(), media_service=BlockingService())
    first = asyncio.create_task(
        application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}", update_id=10))
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    await application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}", update_id=11))
    release.set()
    await first

    assert "A YouTube task is already running. Try again after it finishes." in sent_texts(session)
    assert sum(isinstance(method, SendVideo) for method in session.methods) == 1


async def test_publish_copies_replied_video_to_the_single_configured_channel(bot_and_session):
    bot, session = bot_and_session
    application = create_bot_application(settings(), media_service=AsyncMock())

    await application.dispatcher.feed_update(bot, update("/publish", reply_video=True))

    copies = [method for method in session.methods if isinstance(method, CopyMessage)]
    assert len(copies) == 1
    assert copies[0].chat_id == -100123456789
    assert copies[0].from_chat_id == ADMIN_ID
    assert copies[0].message_id == 50
    assert sent_texts(session)[-1] == "Published to the configured channel."


async def test_unexpected_failure_uses_real_error_router_and_safe_logging(capsys):
    session = RecordingSession()
    bot = Bot(BOT_TOKEN, session=session)
    service = AsyncMock()
    service.probe_async.side_effect = RuntimeError("token=private raw third-party response")
    ticks = iter((10.0, 10.125))
    application = create_bot_application(
        settings(),
        media_service=service,
        logger=configure_logging("INFO"),
        clock=lambda: next(ticks),
        correlation_id_factory=lambda: "corr0001",
    )

    await application.dispatcher.feed_update(bot, update(f"/probe {VIDEO_URL}"))

    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    failure = next(record for record in records if record["event"] == "bot_unexpected_failure")
    completion = next(record for record in records if record["event"] == "bot_operation_finished")
    assert failure["correlation_id"] == "corr0001"
    assert failure["operation"] == "probe"
    assert failure["analysis"]["exception_types"] == ["RuntimeError"]
    assert completion == {
        "correlation_id": "corr0001",
        "duration_ms": 125,
        "error_category": "internal_error",
        "event": "bot_operation_finished",
        "level": "info",
        "operation": "probe",
        "outcome": "error",
        "timestamp": completion["timestamp"],
    }
    assert any("unexpected internal error" in text.lower() for text in sent_texts(session))
    assert "private" not in output
    assert "third-party" not in output
    assert application.operation_registry.pending_count == 0


async def test_error_response_failure_is_contained_and_logged(capsys):
    def fail_internal_response(method: TelegramMethod[Any]) -> bool:
        return (
            isinstance(method, SendMessage) and "unexpected internal error" in method.text.lower()
        )

    session = RecordingSession(fail_when=fail_internal_response)
    bot = Bot(BOT_TOKEN, session=session)
    service = AsyncMock()
    service.probe_async.side_effect = RuntimeError("private exception body")
    application = create_bot_application(
        settings(),
        media_service=service,
        logger=configure_logging("INFO"),
        correlation_id_factory=lambda: "corr0002",
    )

    result = await application.dispatcher.feed_update(bot, update(f"/probe {VIDEO_URL}"))

    output = capsys.readouterr().err
    assert result is True
    assert "bot_error_notification_failure" in output
    assert "RuntimeError" in output
    assert "private" not in output
    assert application.operation_registry.pending_count == 0


async def test_dispatcher_preserves_cancellation(bot_and_session):
    bot, _session = bot_and_session
    service = AsyncMock()
    service.acquire_async.side_effect = asyncio.CancelledError()
    application = create_bot_application(settings(), media_service=service)

    with pytest.raises(asyncio.CancelledError):
        await application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}"))


@pytest.mark.parametrize("code", ["credential_like_token_123", "rate_limit", 123])
async def test_unexpected_exception_code_is_never_logged(bot_and_session, capsys, code):
    class ExternalError(RuntimeError):
        pass

    error = ExternalError("private third-party body")
    error.code = code
    bot, session = bot_and_session
    service = AsyncMock()
    service.probe_async.side_effect = error
    application = create_bot_application(
        settings(),
        media_service=service,
        logger=configure_logging("INFO"),
        correlation_id_factory=lambda: "untrusted-code",
    )

    assert await application.dispatcher.feed_update(bot, update(f"/probe {VIDEO_URL}")) is True

    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    failure = next(record for record in records if record["event"] == "bot_unexpected_failure")
    completion = next(record for record in records if record["event"] == "bot_operation_finished")
    assert failure["code"] == completion["error_category"] == "internal_error"
    assert failure["correlation_id"] == completion["correlation_id"] == "untrusted-code"
    assert completion["outcome"] == "error"
    assert "credential_like_token_123" not in output
    assert "private" not in output
    assert any("unexpected internal error" in text.lower() for text in sent_texts(session))
    assert application.operation_registry.pending_count == 0
    assert not application.media_gate.locked()


@pytest.mark.parametrize("operation", ["upload", "publish"])
async def test_telegram_api_failure_uses_safe_policy_and_does_not_retry(
    tmp_path, capsys, operation
):
    failed_type = SendVideo if operation == "upload" else CopyMessage

    class FailingSession(RecordingSession):
        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, failed_type):
                self.methods.append(method)
                raise TelegramAPIError(method, "private Telegram response")
            return await super().make_request(bot, method, timeout)

    session = FailingSession()
    bot = Bot(BOT_TOKEN, session=session)
    service = AsyncMock()
    service.acquire_async.return_value = library_item(tmp_path)
    application = create_bot_application(
        settings(), media_service=service, logger=configure_logging("INFO")
    )
    request = (
        update(f"/download {VIDEO_URL}")
        if operation == "upload"
        else update("/publish", reply_video=True)
    )

    await application.dispatcher.feed_update(bot, request)

    code = f"telegram_{operation}"
    policy = error_record(code)
    assert sent_texts(session)[-1] == f"{policy['message']}\n{policy['action']}"
    assert sum(isinstance(method, failed_type) for method in session.methods) == 1
    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    failure = next(record for record in records if record["event"] == f"bot_{operation}_failure")
    completion = next(record for record in records if record["event"] == "bot_operation_finished")
    assert failure["code"] == completion["error_category"] == code
    assert failure["correlation_id"] == completion["correlation_id"]
    assert completion["outcome"] == "error"
    assert "private" not in output
    assert application.operation_registry.pending_count == 0
    assert not application.media_gate.locked()


async def test_local_io_failure_uses_safe_policy_without_upload(bot_and_session, capsys):
    bot, session = bot_and_session
    service = AsyncMock()
    service.acquire_async.side_effect = OSError("private filesystem path")
    application = create_bot_application(
        settings(), media_service=service, logger=configure_logging("INFO")
    )

    await application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}"))

    policy = error_record("local_io")
    assert sent_texts(session)[-1] == f"{policy['message']}\n{policy['action']}"
    assert not any(isinstance(method, (SendVideo, SendDocument)) for method in session.methods)
    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    failure = next(record for record in records if record["event"] == "bot_media_failure")
    completion = next(record for record in records if record["event"] == "bot_operation_finished")
    assert failure["code"] == completion["error_category"] == "local_io"
    assert completion["outcome"] == "error"
    assert "private" not in output
    assert application.operation_registry.pending_count == 0
    assert not application.media_gate.locked()


async def test_expected_media_error_notification_failure_is_contained(capsys):
    policy = error_record("media_validation")
    session = RecordingSession(
        fail_when=lambda method: (
            isinstance(method, SendMessage) and method.text.startswith(str(policy["message"]))
        )
    )
    bot = Bot(BOT_TOKEN, session=session)
    service = AsyncMock()
    service.acquire_async.side_effect = MediaError(code="media_validation")
    application = create_bot_application(
        settings(), media_service=service, logger=configure_logging("INFO")
    )

    await application.dispatcher.feed_update(bot, update(f"/download {VIDEO_URL}"))

    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    assert [record["event"] for record in records] == [
        "bot_media_failure",
        "bot_error_notification_failure",
        "bot_operation_finished",
    ]
    assert len({record["correlation_id"] for record in records}) == 1
    assert records[-1]["error_category"] == "media_validation"
    assert records[-1]["outcome"] == "error"
    assert "private" not in output
    assert not any(isinstance(method, (SendVideo, SendDocument)) for method in session.methods)
    assert len(sent_texts(session)) == 2
    assert application.operation_registry.pending_count == 0
    assert not application.media_gate.locked()
