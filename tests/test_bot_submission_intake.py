import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetMe, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    MessageEntity,
    Update,
    User,
    Video,
)

from cats_channel.bot import create_bot_application
from cats_channel.bot.entry import ReplyTarget
from cats_channel.bot.flow import PrivateEntryStates
from cats_channel.config import Settings
from cats_channel.diagnostics import configure_logging
from cats_channel.errors import MediaError
from cats_channel.intake import IntakeError, IntakeResult, SourceOption
from cats_channel.reply_tokens import new_reply_token

ADMIN_ID = 42
TOKEN = "123456:TEST_TOKEN"


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.methods = []

    async def close(self):
        pass

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        self.methods.append(method)
        if isinstance(method, GetMe):
            return User(id=bot.id, is_bot=True, first_name="Cats", username="cats_test_bot")
        return Message(
            message_id=100,
            date=datetime.now(UTC),
            chat=Chat(id=ADMIN_ID, type="private"),
            text=getattr(method, "text", None),
        )

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""


def settings():
    return Settings(
        _env_file=None,
        bot_token=TOKEN,
        admin_user_id=ADMIN_ID,
        channel_id="-100123",
    )


def message_update(
    *,
    update_id=1,
    text=None,
    video=None,
    caption=None,
    user_id=ADMIN_ID,
    chat_type="private",
):
    entities = None
    if text and text.startswith("/"):
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type=chat_type),
            from_user=User(id=user_id, is_bot=False, first_name="Admin"),
            text=text,
            entities=entities,
            video=video,
            caption=caption,
        ),
    )


def callback_update(thread_id, *, update_id=2):
    user = User(id=ADMIN_ID, is_bot=False, first_name="Admin")
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id="callback-id",
            from_user=user,
            chat_instance="private",
            data=f"postsrc:{thread_id}",
            message=Message(
                message_id=50,
                date=datetime.now(UTC),
                chat=Chat(id=ADMIN_ID, type="private"),
                from_user=user,
                text="prompt",
            ),
        ),
    )


def application(*, resolver=None, logger=None, correlation_id_factory=None):
    session = RecordingSession()
    bot = Bot(TOKEN, session=session)
    intake = AsyncMock()
    intake.list_source_options.return_value = ()
    intake.process.return_value = IntakeResult(
        "created", str(uuid4()), str(uuid4()), str(uuid4()), "normal_append"
    )
    media = AsyncMock()
    adapter = AsyncMock()
    app = create_bot_application(
        settings(),
        bot=bot,
        media_service=media,
        intake_service=intake,
        telegram_media_adapter=adapter,
        reply_target_resolver=resolver,
        logger=logger,
        correlation_id_factory=correlation_id_factory,
    )
    return app, bot, session, intake, media, adapter


async def test_post_and_submit_enter_the_same_pending_media_flow():
    app, bot, session, intake, *_ = application()
    await app.dispatcher.feed_update(bot, message_update(text="/post"))
    state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    assert await state.get_state() == PrivateEntryStates.reply_entry.state
    assert await state.get_data() == {}
    assert "Send one Telegram video" in session.methods[-1].text
    intake.list_source_options.assert_awaited_once()

    await app.dispatcher.feed_update(bot, message_update(update_id=2, text="/submit"))
    assert await state.get_state() == PrivateEntryStates.reply_entry.state
    assert intake.list_source_options.await_count == 2


async def test_post_intake_remains_private_and_admin_only():
    app, bot, _session, intake, *_ = application()
    await app.dispatcher.feed_update(bot, message_update(text="/post", user_id=99))
    await app.dispatcher.feed_update(
        bot, message_update(update_id=2, text="/post", chat_type="group")
    )
    intake.list_source_options.assert_not_awaited()


async def test_selected_source_and_native_video_create_only_pending_intake():
    thread_id = str(uuid4())
    app, bot, _session, intake, _media, adapter = application()
    intake.list_source_options.return_value = (SourceOption(thread_id, "telegram", "Cat source"),)
    adapter.acquire.return_value = object()

    async def process(**kwargs):
        assert await kwargs["acquire"]() is adapter.acquire.return_value
        return IntakeResult("created", str(uuid4()), str(uuid4()), thread_id, "normal_append")

    intake.process.side_effect = process
    await app.dispatcher.feed_update(bot, message_update(text="/post"))
    await app.dispatcher.feed_update(bot, callback_update(thread_id))
    await app.dispatcher.feed_update(
        bot,
        message_update(
            update_id=3,
            video=Video(
                file_id="file-id",
                file_unique_id="unique-id",
                width=360,
                height=640,
                duration=10,
            ),
        ),
    )

    placement = intake.require_compatible_provider.await_args.args[0]
    assert placement.mode == "normal_append" and placement.thread_id == thread_id
    intake.process.assert_awaited_once()
    assert intake.process.await_args.kwargs["placement"] == placement
    adapter.acquire.assert_awaited_once()
    state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    assert await state.get_state() is None


async def test_deep_link_keeps_exact_parent_for_pending_intake():
    target = ReplyTarget(str(uuid4()), str(uuid4()))
    resolver = AsyncMock()
    resolver.resolve.return_value = target
    app, bot, _session, intake, media, _adapter = application(resolver=resolver)
    media.acquire_async.return_value = object()
    token = new_reply_token()
    await app.dispatcher.feed_update(bot, message_update(text=f"/start catreply_{token}"))

    async def process(**kwargs):
        assert kwargs["placement"].mode == "interactive_reply"
        assert kwargs["placement"].thread_id == target.thread_id
        assert kwargs["placement"].selected_parent_post_id == target.post_id
        return IntakeResult(
            "created", str(uuid4()), str(uuid4()), target.thread_id, "interactive_reply"
        )

    intake.process.side_effect = process
    await app.dispatcher.feed_update(
        bot,
        message_update(update_id=2, text="https://youtu.be/abcdefghijk"),
    )
    intake.process.assert_awaited_once()


@pytest.mark.parametrize("replacement", ["/cancel", "/post"])
async def test_replacement_during_provider_lookup_does_not_acquire_or_clear_new_flow(replacement):
    thread_id = str(uuid4())
    app, bot, session, intake, _media, adapter = application()
    intake.list_source_options.return_value = (SourceOption(thread_id, "telegram", "Cat source"),)
    started, release = asyncio.Event(), asyncio.Event()

    async def check_provider(*_args):
        started.set()
        await release.wait()

    intake.require_compatible_provider.side_effect = check_provider
    await app.dispatcher.feed_update(bot, message_update(text="/post"))
    await app.dispatcher.feed_update(bot, callback_update(thread_id))
    pending = asyncio.create_task(
        app.dispatcher.feed_update(
            bot,
            message_update(
                update_id=3,
                video=Video(
                    file_id="file-id",
                    file_unique_id="unique-id",
                    width=360,
                    height=640,
                    duration=10,
                ),
            ),
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        await app.dispatcher.feed_update(bot, message_update(update_id=4, text=replacement))
        state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
        expected_state, expected_data = await state.get_state(), await state.get_data()
        release.set()
        await asyncio.wait_for(pending, 2)
        intake.process.assert_not_awaited()
        adapter.acquire.assert_not_awaited()
        assert await state.get_state() == expected_state
        assert await state.get_data() == expected_data
        assert not any(
            "Accepted as pending" in str(getattr(method, "text", "")) for method in session.methods
        )
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_cancel_supersedes_slow_intake_before_persistence():
    thread_id = str(uuid4())
    app, bot, _session, intake, _media, adapter = application()
    intake.list_source_options.return_value = (SourceOption(thread_id, "telegram", "Cat source"),)
    started = asyncio.Event()
    release = asyncio.Event()

    async def acquire(*_args, **_kwargs):
        started.set()
        await release.wait()
        return object()

    adapter.acquire.side_effect = acquire

    async def process(**kwargs):
        await kwargs["acquire"]()
        if not await kwargs["continue_if"]():
            raise IntakeError("intake_superseded")
        raise AssertionError("superseded intake reached persistence")

    intake.process.side_effect = process
    await app.dispatcher.feed_update(bot, message_update(text="/post"))
    await app.dispatcher.feed_update(bot, callback_update(thread_id))
    pending = asyncio.create_task(
        app.dispatcher.feed_update(
            bot,
            message_update(
                update_id=3,
                video=Video(
                    file_id="file-id",
                    file_unique_id="unique-id",
                    width=360,
                    height=640,
                    duration=10,
                ),
            ),
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    await app.dispatcher.feed_update(bot, message_update(update_id=4, text="/cancel"))
    release.set()
    await pending

    state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    assert await state.get_state() is None
    intake.process.assert_awaited_once()


async def test_invalid_native_media_is_rejected_without_clearing_the_retryable_flow():
    thread_id = str(uuid4())
    app, bot, session, intake, _media, adapter = application()
    intake.list_source_options.return_value = (SourceOption(thread_id, "telegram", "Cat source"),)
    adapter.acquire.side_effect = MediaError(code="media_validation")

    async def process(**kwargs):
        await kwargs["acquire"]()

    intake.process.side_effect = process
    await app.dispatcher.feed_update(bot, message_update(text="/post"))
    await app.dispatcher.feed_update(bot, callback_update(thread_id))
    await app.dispatcher.feed_update(
        bot,
        message_update(
            update_id=3,
            video=Video(
                file_id="file-id",
                file_unique_id="unique-id",
                width=360,
                height=640,
                duration=10,
            ),
        ),
    )

    state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    assert await state.get_state() == PrivateEntryStates.reply_entry.state
    assert any(
        "playback validation" in str(getattr(method, "text", "")) for method in session.methods
    )


async def test_intake_completion_log_is_allowlisted_and_secret_safe(capsys):
    thread_id = str(uuid4())
    app, bot, _session, intake, _media, adapter = application(
        logger=configure_logging("INFO"),
        correlation_id_factory=lambda: "intake-log-1",
    )
    intake.list_source_options.return_value = (SourceOption(thread_id, "telegram", "Cat source"),)
    adapter.acquire.return_value = object()

    async def process(**kwargs):
        await kwargs["acquire"]()
        return IntakeResult("created", str(uuid4()), str(uuid4()), thread_id, "normal_append")

    intake.process.side_effect = process
    await app.dispatcher.feed_update(bot, message_update(text="/post"))
    await app.dispatcher.feed_update(bot, callback_update(thread_id))
    await app.dispatcher.feed_update(
        bot,
        message_update(
            update_id=3,
            caption="private-caption-secret",
            video=Video(
                file_id="private-file-id",
                file_unique_id="private-unique-id",
                width=360,
                height=640,
                duration=10,
            ),
        ),
    )

    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    completion = records[-1]
    assert completion["operation"] == "post_intake"
    assert completion["outcome"] == "pending_created"
    assert completion["correlation_id"] == "intake-log-1"
    assert "private-caption-secret" not in output
    assert "private-file-id" not in output
    assert "private-unique-id" not in output
    assert thread_id not in output
