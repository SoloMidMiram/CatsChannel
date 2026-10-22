import asyncio
from contextlib import asynccontextmanager
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


@pytest.mark.parametrize("replacement", ["/cancel", "/post"])
async def test_replacement_during_handoff_cannot_commit_old_media(
    tmp_path, monkeypatch, replacement
):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'handoff.sqlite3').as_posix()}")
    await database.create_schema_for_tests()
    intake = SubmissionIntakeService(database.unit_of_work, LibraryManifestSourceResolver())
    started, release = asyncio.Event(), asyncio.Event()
    issue = intake._submissions.issue_handoff

    async def slow_issue(*args, **kwargs):
        issued = await issue(*args, **kwargs)
        started.set()
        await release.wait()
        return issued

    monkeypatch.setattr(intake._submissions, "issue_handoff", slow_issue)
    submit = AsyncMock(wraps=intake._submissions.submit)
    monkeypatch.setattr(intake._submissions, "submit", submit)
    session = RecordingSession()
    bot = Bot(TOKEN, session=session)
    media = AsyncMock()
    media.acquire_async.return_value = library_item(tmp_path)
    app = create_bot_application(settings(), bot=bot, media_service=media, intake_service=intake)
    pending = None
    try:
        await app.dispatcher.feed_update(bot, message_update(text="/post"))
        pending = asyncio.create_task(
            app.dispatcher.feed_update(
                bot,
                message_update(update_id=2, text="https://youtu.be/abcdefghijk"),
            )
        )
        await asyncio.wait_for(started.wait(), 2)
        await app.dispatcher.feed_update(bot, message_update(update_id=3, text=replacement))
        state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
        expected = (await state.get_state(), await state.get_data())
        release.set()
        await asyncio.wait_for(pending, 2)
        submit.assert_not_awaited()
        async with database.unit_of_work() as uow:
            assert await uow.projections.get_by_reference(TelegramMessageRef(ADMIN_ID, 2)) is None
        assert (await state.get_state(), await state.get_data()) == expected
        assert not any(
            "Accepted as pending" in str(getattr(m, "text", "")) for m in session.methods
        )
        assert intake.pending_count == app.flow_coordinator.pending_count == 0
    finally:
        release.set()
        if pending is not None:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await database.dispose()


@pytest.mark.parametrize("replacement", ["/cancel", "/post"])
async def test_replacement_waits_for_started_commit_and_preserves_its_new_state(
    tmp_path,
    monkeypatch,
    replacement,
):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'commit.sqlite3').as_posix()}")
    await database.create_schema_for_tests()
    intake = SubmissionIntakeService(database.unit_of_work, LibraryManifestSourceResolver())
    started, release, replacing = asyncio.Event(), asyncio.Event(), asyncio.Event()
    submit = intake._submissions.submit

    async def slow_submit(*args, **kwargs):
        started.set()
        await release.wait()
        return await submit(*args, **kwargs)

    monkeypatch.setattr(intake._submissions, "submit", slow_submit)
    session = RecordingSession()
    bot = Bot(TOKEN, session=session)
    media = AsyncMock()
    media.acquire_async.return_value = library_item(tmp_path)
    app = create_bot_application(settings(), bot=bot, media_service=media, intake_service=intake)
    pending = command = None
    try:
        await app.dispatcher.feed_update(bot, message_update(text="/post"))
        replace = app.flow_coordinator.replace

        @asynccontextmanager
        async def observed_replace(state):
            replacing.set()
            async with replace(state) as lease:
                yield lease

        monkeypatch.setattr(app.flow_coordinator, "replace", observed_replace)
        pending = asyncio.create_task(
            app.dispatcher.feed_update(
                bot,
                message_update(update_id=2, text="https://youtu.be/abcdefghijk"),
            )
        )
        await asyncio.wait_for(started.wait(), 2)
        command = asyncio.create_task(
            app.dispatcher.feed_update(
                bot,
                message_update(update_id=3, text=replacement),
            )
        )
        await asyncio.wait_for(replacing.wait(), 2)
        assert not command.done()  # No cancellation acknowledgement mid-commit.
        release.set()
        await asyncio.wait_for(asyncio.gather(pending, command), 2)
        async with database.unit_of_work() as uow:
            projection = await uow.projections.get_by_reference(TelegramMessageRef(ADMIN_ID, 2))
            assert projection is not None
            assert await uow.intents.get_for_submission(projection.submission_id) is not None
        state = app.dispatcher.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
        expected = PrivateEntryStates.reply_entry.state if replacement == "/post" else None
        assert await state.get_state() == expected
        assert await state.get_data() == {}
        assert any("Accepted as pending" in str(getattr(m, "text", "")) for m in session.methods)
        assert intake.pending_count == app.flow_coordinator.pending_count == 0
    finally:
        release.set()
        tasks = [task for task in (pending, command) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await database.dispose()


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
