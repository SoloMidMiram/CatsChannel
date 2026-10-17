import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from pydantic import ValidationError
from test_bot_application import (
    ADMIN_ID,
    BOT_TOKEN,
    HELP_TEXT,
    RecordingSession,
    sent_texts,
    settings,
    update,
)

from cats_channel.bot import create_bot_application
from cats_channel.bot.entry import (
    EntryContractError,
    ModerationCallback,
    ReplyTarget,
    build_reply_link,
    new_reply_token,
    parse_reply_payload,
)
from cats_channel.bot.flow import (
    PrivateEntryContext,
    PrivateEntryStates,
    PrivateFlowCoordinator,
    read_private_entry,
)
from cats_channel.diagnostics import configure_logging


def context(application, bot, *, user_id=ADMIN_ID, chat_id=ADMIN_ID):
    return FSMContext(
        application.dispatcher.storage,
        StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=user_id),
    )


def make_app(resolver=None, session=None):
    session = session or RecordingSession()
    bot = Bot(BOT_TOKEN, session=session)
    application = create_bot_application(
        settings(), bot=bot, media_service=AsyncMock(), reply_target_resolver=resolver
    )
    return application, bot, session


def test_reply_link_is_opaque_and_round_trips_without_network():
    token = new_reply_token()
    link = build_reply_link("@cats_test_bot", token)
    payload = link.split("?start=", 1)[1]
    assert link.startswith("https://t.me/cats_test_bot?start=catreply_")
    assert len(payload) <= 64
    assert parse_reply_payload(payload) == token
    assert new_reply_token() != token


def test_canonical_zero_bytes_token_is_valid_syntax():
    # Token syntax does not establish issuance or authorization; the resolver does.
    token = "A" * 43
    link = build_reply_link("cats_test_bot", token)
    assert parse_reply_payload(link.split("?start=", 1)[1]) == token


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "catreply_123",
        "catreply_" + "a" * 43,
        "handoff_" + "A" * 43,
        "catreply_" + "A" * 43 + " extra",
        "catreply_" + "A" * 42 + "=",
        "catreply_-100123:7",
        "catreply_" + "A" * 64,
    ],
)
def test_reply_parser_rejects_invalid_noncanonical_and_coordinate_payloads(payload):
    with pytest.raises(EntryContractError) as caught:
        parse_reply_payload(payload)
    assert str(caught.value) == "Invalid reply entry"


@pytest.mark.parametrize("username", ["cats?start=private", "cat/name", "https://t.me/cat", ""])
def test_link_builder_rejects_username_injection(username):
    with pytest.raises(EntryContractError):
        build_reply_link(username, new_reply_token())


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_moderation_callback_round_trip_uses_internal_uuid(action):
    identifier = str(uuid4())
    payload = ModerationCallback(action=action, submission_id=identifier).pack()
    assert len(payload.encode()) <= 64
    parsed = ModerationCallback.unpack(payload)
    assert parsed.action == action and parsed.submission_id == identifier


@pytest.mark.parametrize(
    "action,identifier",
    [
        ("delete", str(uuid4())),
        ("approve", "123"),
        ("reject", "-100123:7"),
        ("approve", "private-message"),
    ],
)
def test_callback_rejects_actions_and_external_identifiers(action, identifier):
    with pytest.raises((ValueError, ValidationError)):
        ModerationCallback(action=action, submission_id=identifier)


@pytest.mark.parametrize(
    "payload",
    ["other:approve:123", "catmod:delete:123", "catmod:approve:-100:7", "catmod:approve:123"],
)
def test_callback_unpack_rejects_untrusted_wire_payload(payload):
    with pytest.raises((ValueError, TypeError)):
        ModerationCallback.unpack(payload)


async def test_real_dispatcher_resolves_authorized_target_before_storing_only_internal_ids():
    token = new_reply_token()
    target = ReplyTarget(str(uuid4()), str(uuid4()))
    resolver = AsyncMock()
    resolver.resolve.return_value = target
    app, bot, session = make_app(resolver)
    state = context(app, bot)
    await app.dispatcher.feed_update(bot, update(f"/start catreply_{token}"))
    resolver.resolve.assert_awaited_once_with(token, actor_id=ADMIN_ID)
    assert await state.get_state() == PrivateEntryStates.reply_entry.state
    assert await state.get_data() == {
        "thread_id": target.thread_id,
        "parent_post_id": target.post_id,
    }
    assert token not in str(await state.get_data())
    assert "Use /cancel" in sent_texts(session)[-1]
    assert await read_private_entry(state) == PrivateEntryContext(target.thread_id, target.post_id)
    assert app.flow_coordinator.pending_count == 0


@pytest.mark.parametrize(
    "payload,known_shape", [("bad-private-token", False), ("catreply_" + "A" * 43, True)]
)
async def test_invalid_and_unknown_links_clear_previous_state_without_echoing_payload(
    payload, known_shape
):
    resolver = AsyncMock()
    resolver.resolve.return_value = None
    app, bot, session = make_app(resolver)
    state = context(app, bot)
    await state.set_state(PrivateEntryStates.reply_entry)
    await state.set_data({"parent_post_id": str(uuid4())})
    await app.dispatcher.feed_update(bot, update(f"/start {payload}"))
    assert await state.get_state() is None and await state.get_data() == {}
    assert (resolver.resolve.await_count == 1) == known_shape
    assert "invalid or unavailable" in sent_texts(session)[-1]
    assert payload not in sent_texts(session)[-1]


async def test_default_resolver_fails_closed():
    app, bot, session = make_app()
    await app.dispatcher.feed_update(bot, update(f"/start catreply_{new_reply_token()}"))
    assert await context(app, bot).get_state() is None
    assert "invalid or unavailable" in sent_texts(session)[-1]


@pytest.mark.parametrize(
    "command", ["/start", "/help", "/probe", "/download", "/publish", "/cancel"]
)
async def test_recognized_commands_reset_state_and_private_data(command):
    app, bot, session = make_app()
    state = context(app, bot)
    await state.set_state(PrivateEntryStates.reply_entry)
    await state.set_data({"thread_id": str(uuid4()), "private_text": "old private text"})
    await app.dispatcher.feed_update(bot, update(command))
    assert await state.get_state() is None and await state.get_data() == {}
    assert sent_texts(session)
    if command in {"/start", "/help"}:
        assert sent_texts(session) == [HELP_TEXT]
    assert app.flow_coordinator.pending_count == 0


async def test_unknown_message_does_not_replace_active_entry_or_store_message_text():
    app, bot, _ = make_app()
    state = context(app, bot)
    current = PrivateEntryContext(str(uuid4()), str(uuid4())).to_data()
    await state.set_state(PrivateEntryStates.reply_entry)
    await state.set_data(current)
    await app.dispatcher.feed_update(bot, update("unrelated private text"))
    assert await state.get_data() == current
    assert "private text" not in str(await state.get_data())


async def test_command_for_another_bot_does_not_replace_entry():
    app, bot, session = make_app()
    state = context(app, bot)
    current = PrivateEntryContext(str(uuid4()), str(uuid4())).to_data()
    await state.set_state(PrivateEntryStates.reply_entry)
    await state.set_data(current)
    await app.dispatcher.feed_update(bot, update("/help@some_other_bot"))
    assert await state.get_data() == current
    assert sent_texts(session) == []


@pytest.mark.parametrize("user_id,chat_type", [(999, "private"), (ADMIN_ID, "group")])
async def test_filters_run_before_resolver_or_fsm_reset(user_id, chat_type):
    resolver = AsyncMock()
    app, bot, session = make_app(resolver)
    state = context(app, bot, user_id=user_id, chat_id=user_id)
    await state.set_state(PrivateEntryStates.reply_entry)
    await state.set_data({"thread_id": str(uuid4())})
    before = await state.get_data()
    await app.dispatcher.feed_update(
        bot, update(f"/start catreply_{new_reply_token()}", user_id=user_id, chat_type=chat_type)
    )
    assert await state.get_data() == before
    resolver.resolve.assert_not_called()
    assert session.methods == []


async def test_new_command_wins_over_slow_reply_resolution():
    entered, release = asyncio.Event(), asyncio.Event()

    async def resolve(token, *, actor_id):
        entered.set()
        await release.wait()
        return ReplyTarget(str(uuid4()), str(uuid4()))

    resolver = AsyncMock()
    resolver.resolve.side_effect = resolve
    app, bot, session = make_app(resolver)
    first = asyncio.create_task(
        app.dispatcher.feed_update(bot, update(f"/start catreply_{new_reply_token()}"))
    )
    await asyncio.wait_for(entered.wait(), 1)
    await app.dispatcher.feed_update(bot, update("/cancel", update_id=2))
    release.set()
    await first
    assert await context(app, bot).get_state() is None
    assert await context(app, bot).get_data() == {}
    assert sent_texts(session) == ["Cancelled."]
    assert app.flow_coordinator.pending_count == 0


async def test_failed_entry_confirmation_does_not_leave_active_state():
    resolver = AsyncMock()
    resolver.resolve.return_value = ReplyTarget(str(uuid4()), str(uuid4()))
    session = RecordingSession(
        fail_when=lambda method: "Reply context selected" in str(getattr(method, "text", ""))
    )
    app, bot, _ = make_app(resolver, session)
    await app.dispatcher.feed_update(bot, update(f"/start catreply_{new_reply_token()}"))
    assert await context(app, bot).get_state() is None
    assert await context(app, bot).get_data() == {}
    assert app.flow_coordinator.pending_count == 0


async def test_invalid_stored_context_is_cleared():
    app, bot, _ = make_app()
    state = context(app, bot)
    await state.set_state(PrivateEntryStates.reply_entry)
    await state.set_data({"thread_id": "123", "parent_post_id": "456", "message_text": "private"})
    with pytest.raises(EntryContractError):
        await read_private_entry(state)
    assert await state.get_state() is None and await state.get_data() == {}


async def test_resolver_cancellation_does_not_leave_state_or_registry_entries():
    resolver = AsyncMock()
    resolver.resolve.side_effect = asyncio.CancelledError()
    app, bot, session = make_app(resolver)
    with pytest.raises(asyncio.CancelledError):
        await app.dispatcher.feed_update(bot, update(f"/start catreply_{new_reply_token()}"))
    assert await context(app, bot).get_data() == {}
    assert await context(app, bot).get_state() is None
    assert app.operation_registry.pending_count == app.flow_coordinator.pending_count == 0
    assert sent_texts(session) == []


async def test_entry_cancellation_remains_primary_when_partial_state_clear_fails():
    class FailingState:
        key = StorageKey(bot_id=1, chat_id=2, user_id=3)

        def __init__(self):
            self.clear_count = 0

        async def clear(self):
            self.clear_count += 1
            if self.clear_count > 1:
                raise RuntimeError("state cleanup failed")

        async def set_data(self, data):
            pass

        async def set_state(self, value):
            pass

    async def cancelled_notification():
        raise asyncio.CancelledError

    state = FailingState()
    coordinator = PrivateFlowCoordinator()
    with pytest.raises(asyncio.CancelledError) as caught:
        async with coordinator.replace(state) as lease:
            await lease.select(
                PrivateEntryContext(str(uuid4()), str(uuid4())), cancelled_notification
            )

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert state.clear_count == 2
    assert coordinator.pending_count == 0


async def test_unexpected_resolver_failure_logs_no_token_or_private_body(capsys):
    token = new_reply_token()
    resolver = AsyncMock()
    resolver.resolve.side_effect = RuntimeError(f"private-resolver-body {token}")
    app, bot, session = make_app(resolver)
    configure_logging("INFO")
    await app.dispatcher.feed_update(bot, update(f"/start catreply_{token}"))
    output = capsys.readouterr().err
    assert "bot_unexpected_failure" in output
    assert token not in output and "private-resolver-body" not in output
    assert any("unexpected internal error" in text.lower() for text in sent_texts(session))
    assert await context(app, bot).get_state() is None
    assert app.operation_registry.pending_count == app.flow_coordinator.pending_count == 0
