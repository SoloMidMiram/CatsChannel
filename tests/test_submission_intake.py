from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_submission_contracts import library_item
from test_submission_service import telegram_media

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from cats_channel.intake import IntakePlacement, SubmissionIntakeService
from cats_channel.persistence import Database, SourceIdentity, TelegramMessageRef
from cats_channel.reply_chains.errors import ReplyChainError
from cats_channel.reply_chains.service import ReplyChainService
from cats_channel.reply_tokens import ReplyTarget
from cats_channel.submissions import LibraryManifestSourceResolver, local_media_from_library_item


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


@pytest.fixture
async def database(tmp_path):
    value = Database(sqlite_url(tmp_path / "intake.sqlite3"))
    await value.create_schema_for_tests()
    try:
        yield value
    finally:
        await value.dispose()


async def youtube_parent(database):
    async with database.unit_of_work() as uow:
        thread = await uow.threads.get_or_create(SourceIdentity("youtube", "UC-parent"))
        submission = await uow.submissions.create(
            source_provider="youtube",
            source_media_id="parent-video",
            source_channel_id="UC-parent",
            source_identity_status="verified",
            thread_id=thread.id,
            status="validated",
        )
    chains = ReplyChainService(database.unit_of_work)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    parent = await chains.finalize_intent(intent.id)
    return thread, parent


def intake(database, *, chains=None):
    return SubmissionIntakeService(
        database.unit_of_work,
        LibraryManifestSourceResolver(),
        reply_chains=chains,
        clock=lambda: datetime(2026, 10, 18, 8, tzinfo=UTC),
    )


async def test_normal_local_intake_creates_pending_intent_without_finalizing(database, tmp_path):
    media = local_media_from_library_item(library_item(tmp_path))
    acquire = AsyncMock(return_value=media)
    reference = TelegramMessageRef(42, 100)

    result = await intake(database).process(
        actor_id=42,
        inbound_reference=reference,
        placement=IntakePlacement.normal(),
        acquire=acquire,
    )

    assert result.disposition == "created"
    assert result.lifecycle == "pending"
    assert result.mode == "normal_append"
    acquire.assert_awaited_once_with()
    async with database.unit_of_work() as uow:
        submission = await uow.submissions.get(result.submission_id)
        intent = await uow.intents.get_for_submission(result.submission_id)
        projection = await uow.projections.get_by_reference(reference)
        post = await uow.threads.get_post_for_submission(result.submission_id)
        handoff = await uow.handoffs.get_for_submission(result.submission_id)
    assert submission is not None
    assert submission.placement_mode == "normal_append"
    assert submission.selected_parent_post_id is None
    assert intent is not None and intent.id == result.intent_id
    assert intent.selected_parent_post_id is None
    assert projection is not None and projection.submission_id == submission.id
    assert handoff is not None and handoff.actor_id == 42
    assert post is None


async def test_exact_telegram_intake_keeps_provenance_and_does_not_move_tail(database):
    thread, parent = await youtube_parent(database)
    media = telegram_media("native-file", chat_id=42, message_id=200)
    reference = media.reference

    result = await intake(database).process(
        actor_id=42,
        inbound_reference=reference,
        placement=IntakePlacement.interactive(ReplyTarget(parent.post_id, thread.id)),
        acquire=AsyncMock(return_value=media),
    )

    async with database.unit_of_work() as uow:
        submission = await uow.submissions.get(result.submission_id)
        intent = await uow.intents.get(result.intent_id)
        stored_thread = await uow.threads.get(thread.id)
        post = await uow.threads.get_post_for_submission(result.submission_id)
    assert submission is not None
    assert submission.source_provider == "telegram"
    assert submission.source_identity_status == "unresolved"
    assert submission.source_channel_id is None
    assert submission.placement_mode == "interactive_reply"
    assert submission.selected_parent_post_id == parent.post_id
    assert intent is not None and intent.selected_parent_post_id == parent.post_id
    assert stored_thread.tail_post_id == parent.post_id
    assert post is None


async def test_replay_after_submission_commit_creates_only_missing_exact_intent(
    database, monkeypatch
):
    thread, parent = await youtube_parent(database)
    reference = TelegramMessageRef(42, 300)
    media = telegram_media("partial-file", chat_id=42, message_id=300)
    placement = IntakePlacement.interactive(ReplyTarget(parent.post_id, thread.id))
    chains = ReplyChainService(database.unit_of_work)
    original = chains.create_interactive_intent
    attempts = 0

    async def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ReplyChainError("reply_chain_unavailable")
        return await original(*args, **kwargs)

    monkeypatch.setattr(chains, "create_interactive_intent", fail_once)
    first_acquire = AsyncMock(return_value=media)
    with pytest.raises(ReplyChainError) as caught:
        await intake(database, chains=chains).process(
            actor_id=42,
            inbound_reference=reference,
            placement=placement,
            acquire=first_acquire,
        )
    assert caught.value.code == "reply_chain_unavailable"
    first_acquire.assert_awaited_once_with()
    async with database.unit_of_work() as uow:
        projection = await uow.projections.get_by_reference(reference)
        assert projection is not None
        submission_id = projection.submission_id
        assert await uow.intents.get_for_submission(submission_id) is None

    second_acquire = AsyncMock(side_effect=AssertionError("media transferred twice"))
    recovered = await intake(database).process(
        actor_id=42,
        inbound_reference=reference,
        placement=placement,
        acquire=second_acquire,
    )

    assert recovered.disposition == "recovered"
    assert recovered.submission_id == submission_id
    second_acquire.assert_not_awaited()
    async with database.unit_of_work() as uow:
        intent = await uow.intents.get_for_submission(submission_id)
        submission = await uow.submissions.get(submission_id)
    assert intent is not None and intent.id == recovered.intent_id
    assert intent.selected_parent_post_id == parent.post_id
    assert submission.selected_parent_post_id == parent.post_id


async def test_replayed_completed_update_returns_existing_without_transfer(database, tmp_path):
    media = local_media_from_library_item(library_item(tmp_path))
    reference = TelegramMessageRef(42, 400)
    placement = IntakePlacement.normal()
    service = intake(database)
    created = await service.process(
        actor_id=42,
        inbound_reference=reference,
        placement=placement,
        acquire=AsyncMock(return_value=media),
    )
    duplicate_transfer = AsyncMock(side_effect=AssertionError("media transferred twice"))

    existing = await service.process(
        actor_id=42,
        inbound_reference=reference,
        placement=placement,
        acquire=duplicate_transfer,
    )

    assert existing.disposition == "existing"
    assert existing.submission_id == created.submission_id
    assert existing.intent_id == created.intent_id
    duplicate_transfer.assert_not_awaited()


async def test_concurrent_replay_serializes_before_transfer(database, tmp_path):
    media = local_media_from_library_item(library_item(tmp_path))
    reference = TelegramMessageRef(42, 500)
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def acquire():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return media

    service = intake(database)
    first = asyncio.create_task(
        service.process(
            actor_id=42,
            inbound_reference=reference,
            placement=IntakePlacement.normal(),
            acquire=acquire,
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    second = asyncio.create_task(
        service.process(
            actor_id=42,
            inbound_reference=reference,
            placement=IntakePlacement.normal(),
            acquire=acquire,
        )
    )
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)

    assert calls == 1
    assert {result.disposition for result in results} == {"created", "existing"}
    assert results[0].submission_id == results[1].submission_id
    assert service.pending_count == 0


async def test_placement_or_owner_mismatch_rejects_replay_without_transfer(database, tmp_path):
    media = local_media_from_library_item(library_item(tmp_path))
    reference = TelegramMessageRef(42, 600)
    service = intake(database)
    await service.process(
        actor_id=42,
        inbound_reference=reference,
        placement=IntakePlacement.normal(),
        acquire=AsyncMock(return_value=media),
    )
    transfer = AsyncMock(side_effect=AssertionError("mismatch transferred media"))

    with pytest.raises(Exception) as owner:
        await service.process(
            actor_id=99,
            inbound_reference=reference,
            placement=IntakePlacement.normal(),
            acquire=transfer,
        )
    assert getattr(owner.value, "code", None) == "intake_conflict"
    transfer.assert_not_awaited()


async def test_cancellation_releases_intake_slot_without_persistence(database):
    reference = TelegramMessageRef(42, 700)
    started = asyncio.Event()

    async def acquire():
        started.set()
        await asyncio.Event().wait()

    service = intake(database)
    task = asyncio.create_task(
        service.process(
            actor_id=42,
            inbound_reference=reference,
            placement=IntakePlacement.normal(),
            acquire=acquire,
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert service.pending_count == 0
    async with database.unit_of_work() as uow:
        assert await uow.projections.get_by_reference(reference) is None
