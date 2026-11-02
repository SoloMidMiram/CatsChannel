"""Read-only destination policy and fail-closed real application startup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.methods import GetMe
from pydantic import ValidationError
from test_bot_application import BOT_TOKEN, RecordingSession, settings

from cats_channel.bot import create_bot_application
from cats_channel.bot.review_isolation import review_destinations, verify_review_isolation
from cats_channel.config import Settings
from cats_channel.errors import MediaError

REVIEW = -100456
DESTINATION = -100123456789


def configured(**updates):
    values = {"reply_entries_enabled": True, "review_channel_id": REVIEW}
    values.update(updates)
    return settings(**values)


def readable_bot(
    *, public_review=False, public_destination=True, can_post=True, can_edit=True, mismatch=False
):
    bot = AsyncMock()
    bot.me.return_value = SimpleNamespace(id=123456)

    async def chat(target):
        public = public_review if target == REVIEW else public_destination
        return SimpleNamespace(
            id=target + 1 if mismatch else target,
            type="channel",
            username="public" if public else None,
        )

    bot.get_chat.side_effect = chat
    bot.get_chat_member.return_value = SimpleNamespace(
        status="administrator", can_post_messages=can_post, can_edit_messages=can_edit
    )
    return bot


async def test_separate_public_destination_requires_private_inspection_without_sends():
    bot = readable_bot()
    await verify_review_isolation(configured(), bot)
    assert [call.args[0] for call in bot.get_chat.await_args_list] == [REVIEW, DESTINATION]
    bot.send_video.assert_not_awaited()
    bot.edit_message_caption.assert_not_awaited()


@pytest.mark.parametrize(
    "updates",
    [
        {"review_channel_id": None},
        {"channel_id": None},
        {"channel_id": "@alias"},
        {"review_channel_id": DESTINATION},
        {"review_channel_id": 0},
        {"review_channel_id": 42},
        {"admin_user_id": None},
        {"channel_id": "42"},
    ],
)
async def test_invalid_configuration_fails_before_network(updates):
    bot = readable_bot()
    with pytest.raises((MediaError, ValidationError)) as error:
        await verify_review_isolation(configured(**updates), bot)
    if isinstance(error.value, MediaError):
        assert error.value.code == "review_configuration"
    bot.me.assert_not_awaited()
    bot.get_chat.assert_not_awaited()


async def test_same_private_channel_needs_explicit_pilot_mode():
    config = configured(channel_id=str(REVIEW), review_isolation_mode="private_pilot")
    bot = readable_bot(public_review=False)
    await verify_review_isolation(config, bot)
    assert bot.get_chat.await_count == 1
    bot = readable_bot(public_review=True)
    with pytest.raises(MediaError):
        await verify_review_isolation(config, bot)


@pytest.mark.parametrize(
    "damage", ["public_review", "post", "edit", "lookup", "timeout", "mismatch"]
)
async def test_unverifiable_permissions_or_privacy_fail_closed_and_redact(damage):
    bot = readable_bot(
        public_review=damage == "public_review",
        can_post=damage != "post",
        can_edit=damage != "edit",
        mismatch=damage == "mismatch",
    )
    if damage in {"lookup", "timeout"}:
        bot.get_chat.side_effect = (
            TimeoutError("SECRET")
            if damage == "timeout"
            else RuntimeError("private API token SECRET")
        )
    with pytest.raises(MediaError) as error:
        await verify_review_isolation(configured(), bot)
    assert error.value.code == "review_permissions_unverified"
    assert "SECRET" not in str(error.value)
    bot.send_video.assert_not_awaited()


@pytest.mark.parametrize("valid", [True, False])
async def test_real_application_startup_enforces_gate_before_polling(valid):
    session = RecordingSession()
    bot = Bot(BOT_TOKEN, session=session)
    readable = readable_bot(public_review=not valid)
    bot.get_chat = readable.get_chat
    bot.get_chat_member = readable.get_chat_member
    app = create_bot_application(configured(), bot=bot)
    poll = AsyncMock()
    app.dispatcher.start_polling = poll
    if valid:
        await app.start_polling()
        poll.assert_awaited_once()
    else:
        with pytest.raises(MediaError):
            await app.start_polling()
        poll.assert_not_awaited()
    assert session.closed
    assert all(isinstance(method, GetMe) for method in session.methods)


async def test_fresh_startup_rechecks_changed_configuration_and_permissions():
    config = configured()
    first = readable_bot()
    await verify_review_isolation(config, first)
    config.channel_id = str(REVIEW)
    second = readable_bot()
    with pytest.raises(MediaError):
        await verify_review_isolation(config, second)
    second.get_chat.assert_not_awaited()
    config.channel_id = str(DESTINATION)
    third = readable_bot(can_edit=False)
    with pytest.raises(MediaError):
        await verify_review_isolation(config, third)


def test_unrecognized_pilot_mode_is_not_accepted():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, review_isolation_mode="anything")


def test_legacy_nonpersistent_utility_has_no_implicit_review_destination():
    assert review_destinations(settings()) is None
