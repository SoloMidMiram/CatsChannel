from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from test_bot_submission_intake import (
    ADMIN_ID,
    TOKEN,
    RecordingSession,
    message_update,
    settings,
)
from test_submission_contracts import library_item

from cats_channel.bot import create_bot_application
from cats_channel.bot.flow import PrivateEntryStates
from cats_channel.intake import SubmissionIntakeService
from cats_channel.persistence import Database, TelegramMessageRef
from cats_channel.reply_chains.errors import ReplyChainError
from cats_channel.reply_chains.service import ReplyChainService
from cats_channel.submissions import LibraryManifestSourceResolver


async def test_dispatcher_replay_after_submission_commit_does_not_transfer_twice(
    tmp_path: Path, monkeypatch
):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'dispatcher.sqlite3').as_posix()}")
    await database.create_schema_for_tests()
    chains = ReplyChainService(database.unit_of_work)
    original = chains.create_normal_intent
    attempts = 0

    async def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ReplyChainError("reply_chain_unavailable")
        return await original(*args, **kwargs)

    monkeypatch.setattr(chains, "create_normal_intent", fail_once)
    intake = SubmissionIntakeService(
        database.unit_of_work,
        LibraryManifestSourceResolver(),
        reply_chains=chains,
    )
    session = RecordingSession()
    bot = Bot(TOKEN, session=session)
    media = AsyncMock()
    media.acquire_async.return_value = library_item(tmp_path)
    app = create_bot_application(settings(), bot=bot, media_service=media, intake_service=intake)
    inbound = message_update(update_id=2, text="https://youtu.be/abcdefghijk")
    try:
        await app.dispatcher.feed_update(bot, message_update(text="/post"))
        await app.dispatcher.feed_update(bot, inbound)
        state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
        assert await state.get_state() == PrivateEntryStates.reply_entry.state

        await app.dispatcher.feed_update(bot, inbound)

        media.acquire_async.assert_awaited_once()
        assert attempts == 2
        assert await state.get_state() is None
        async with database.unit_of_work() as uow:
            projection = await uow.projections.get_by_reference(TelegramMessageRef(ADMIN_ID, 2))
            assert projection is not None
            assert await uow.intents.get_for_submission(projection.submission_id) is not None
    finally:
        await database.dispose()
