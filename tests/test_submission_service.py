from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from cats_channel.persistence import Database, SourceIdentity, TelegramMessageRef
from cats_channel.persistence.models import MediaHandoffRequestModel
from cats_channel.submissions import (
    HandoffBinding,
    HandoffClaim,
    MediaValidationEvidence,
    ResolvedSourceIdentity,
    SubmissionError,
    SubmissionRequest,
    SubmissionService,
    SubmissionVideoMetadata,
    ValidatedLocalMedia,
    ValidatedTelegramMedia,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


@pytest.fixture
async def database(tmp_path):
    value = Database(sqlite_url(tmp_path / "submissions.sqlite3"))
    await value.create_schema_for_tests()
    try:
        yield value
    finally:
        await value.dispose()


class MappingResolver:
    def __init__(self, resolutions: dict[str, ResolvedSourceIdentity]) -> None:
        self.resolutions = resolutions

    async def resolve(self, media):
        return self.resolutions[media.source_media_id]


def unresolved() -> ResolvedSourceIdentity:
    return ResolvedSourceIdentity(
        status="unresolved",
        identity=None,
        method="identity_not_verified",
        evidence={"trusted": False},
    )


def verified(
    channel_id: str,
    *,
    channel_name: str | None = "Cats",
    channel_username: str | None = "cats",
) -> ResolvedSourceIdentity:
    return ResolvedSourceIdentity(
        status="verified",
        identity=SourceIdentity(
            provider="youtube",
            channel_id=channel_id,
            channel_name=channel_name,
            channel_username=channel_username,
        ),
        method="adapter_verified",
        evidence={"stable_channel_id": True},
    )


def validation() -> MediaValidationEvidence:
    return MediaValidationEvidence(
        validator="offline-test",
        validated_at=datetime(2026, 10, 17, 10, tzinfo=UTC),
        size_bytes=1024,
        duration_seconds=8.5,
        sha256="b" * 64,
        video_stream_count=1,
        audio_stream_count=1,
        full_decode=True,
    )


def local_media(media_id: str) -> ValidatedLocalMedia:
    return ValidatedLocalMedia(
        source_provider="youtube",
        source_media_id=media_id,
        item_path=f"library/youtube/{media_id}",
        backend="yt_dlp",
        metadata=SubmissionVideoMetadata(
            title=f"Cat {media_id}",
            duration_seconds=8.5,
            width=360,
            height=640,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        ),
        validation=validation(),
        provenance={},
    )


def telegram_media(media_id: str, *, chat_id: int = 200, message_id: int = 9):
    return ValidatedTelegramMedia(
        source_provider="telegram",
        source_media_id=media_id,
        reference=TelegramMessageRef(chat_id=chat_id, message_id=message_id),
        file_id=f"downloadable-{media_id}",
        file_unique_id=media_id,
        metadata=SubmissionVideoMetadata(title=None, duration_seconds=8.5),
        validation=validation(),
        provenance={"adapter": "telegram_native"},
    )


async def create_thread(database, source: SourceIdentity):
    async with database.unit_of_work() as uow:
        return await uow.threads.get_or_create(source)


async def test_verified_identity_and_display_changes_preserve_thread(database):
    first_media = local_media("video-one")
    second_media = local_media("video-two")
    resolver = MappingResolver(
        {
            "video-one": verified("UC-stable", channel_name="Old cats", channel_username="old"),
            "video-two": verified("UC-stable", channel_name="Private cats", channel_username=None),
        }
    )
    service = SubmissionService(database.unit_of_work, resolver)

    first = await service.submit(SubmissionRequest(first_media))
    second = await service.submit(SubmissionRequest(second_media))

    assert first.thread_id == second.thread_id
    assert first.source_identity_status == second.source_identity_status == "verified"
    async with database.unit_of_work() as uow:
        thread = await uow.threads.get(first.thread_id)
        first_record = await uow.submissions.get(first.submission_id)
        second_record = await uow.submissions.get(second.submission_id)
    assert thread is not None
    assert thread.source.channel_name == "Private cats"
    assert thread.source.channel_username is None
    assert first_record.source_channel_name == "Old cats"
    assert first_record.source_channel_username == "old"
    assert second_record.source_channel_name == "Private cats"
    assert second_record.source_channel_username is None


async def test_manual_selection_is_explicit_and_distinct_from_verification(database):
    thread = await create_thread(database, SourceIdentity("youtube", "UC-manual", "Manual"))
    media = local_media("manual-video")
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: unresolved()}),
    )

    result = await service.submit(SubmissionRequest(media=media, selected_thread_id=thread.id))

    assert result.source_identity_status == "user_selected"
    async with database.unit_of_work() as uow:
        stored = await uow.submissions.get(result.submission_id)
    assert stored is not None
    assert stored.thread_id == thread.id
    assert stored.source_identity_status == "user_selected"
    assert stored.provenance["source_resolution"]["status"] == "unresolved"


async def test_unresolved_identity_without_selection_persists_nothing(database):
    media = local_media("unresolved")
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: unresolved()}),
    )

    with pytest.raises(SubmissionError) as error:
        await service.submit(SubmissionRequest(media))

    assert error.value.code == "source_identity_unresolved"
    async with database.unit_of_work() as uow:
        assert await uow.submissions.get_by_source_media("youtube", media.source_media_id) is None


async def test_verified_identity_conflicting_with_manual_selection_rolls_back(database):
    selected = await create_thread(database, SourceIdentity("youtube", "UC-other"))
    media = local_media("conflict-video")
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: verified("UC-verified")}),
    )

    with pytest.raises(SubmissionError) as error:
        await service.submit(SubmissionRequest(media=media, selected_thread_id=selected.id))

    assert error.value.code == "source_identity_conflict"
    async with database.unit_of_work() as uow:
        assert await uow.submissions.get_by_source_media("youtube", media.source_media_id) is None


async def test_duplicate_source_media_is_rejected_across_threads(database):
    first = await create_thread(database, SourceIdentity("youtube", "UC-first"))
    second = await create_thread(database, SourceIdentity("youtube", "UC-second"))
    media = local_media("duplicate-video")
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: unresolved()}),
    )

    accepted = await service.submit(SubmissionRequest(media=media, selected_thread_id=first.id))
    with pytest.raises(SubmissionError) as error:
        await service.submit(SubmissionRequest(media=media, selected_thread_id=second.id))

    assert accepted.thread_id == first.id
    assert error.value.code == "duplicate_media"
    async with database.unit_of_work() as uow:
        stored = await uow.submissions.get_by_source_media("youtube", media.source_media_id)
    assert stored is not None and stored.id == accepted.submission_id


async def test_same_telegram_file_in_different_messages_is_duplicate(database):
    thread = await create_thread(database, SourceIdentity("telegram", "source-chat"))
    first = telegram_media("same-file", chat_id=200, message_id=1)
    second = replace(first, reference=TelegramMessageRef(300, 2), file_id="another-bot-file-id")
    service = SubmissionService(database.unit_of_work, MappingResolver({"same-file": unresolved()}))
    first_binding = HandoffBinding(actor_id=100, conversation_chat_id=200)
    second_binding = HandoffBinding(actor_id=100, conversation_chat_id=300)
    first_token = await service.issue_handoff(first_binding)
    second_token = await service.issue_handoff(second_binding)
    accepted = await service.submit(
        SubmissionRequest(first, thread.id, HandoffClaim(first_token.token, first_binding))
    )
    with pytest.raises(SubmissionError) as caught:
        await service.submit(
            SubmissionRequest(second, thread.id, HandoffClaim(second_token.token, second_binding))
        )
    assert caught.value.code == "duplicate_media"
    async with database.unit_of_work() as uow:
        stored = await uow.submissions.get_by_source_media("telegram", "same-file")
        assert stored.id == accepted.submission_id
        assert await uow.projections.get_by_reference(second.reference) is None
    assert await service.reconcile_handoff(HandoffClaim(second_token.token, second_binding)) is None


@pytest.mark.parametrize(
    "provenance",
    [{"credentials": "private-marker"}, {"media": {"raw_payload": {"token": "private-marker"}}}],
)
async def test_repository_rejects_unreviewed_provenance(database, provenance):
    with pytest.raises(ValueError) as caught:
        async with database.unit_of_work() as uow:
            await uow.submissions.create(
                source_provider="youtube",
                source_media_id="unsafe-provenance",
                media_origin="local_library",
                provenance=provenance,
            )
    assert "private-marker" not in str(caught.value)
    async with database.unit_of_work() as uow:
        assert await uow.submissions.get_by_source_media("youtube", "unsafe-provenance") is None


async def test_telegram_handoff_is_bound_consumed_and_projected_atomically(database):
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    thread = await create_thread(database, SourceIdentity("telegram", "source-chat"))
    media = telegram_media("telegram-unique")
    binding = HandoffBinding(actor_id=100, conversation_chat_id=media.reference.chat_id)
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: unresolved()}),
        clock=lambda: now,
        token_factory=lambda: "A" * 43,
    )
    issued = await service.issue_handoff(binding)
    claim = HandoffClaim(issued.token, binding)

    result = await service.submit(
        SubmissionRequest(media=media, selected_thread_id=thread.id, handoff=claim)
    )

    assert result.disposition == "created"
    async with database.unit_of_work() as uow:
        stored = await uow.submissions.get(result.submission_id)
        projection = await uow.projections.get_by_reference(media.reference)
        handoff = await uow.handoffs.get_bound(
            token_digest=hashlib.sha256(issued.token.encode("ascii")).hexdigest(),
            actor_id=binding.actor_id,
            conversation_chat_id=binding.conversation_chat_id,
            operation=binding.operation,
        )
    assert stored is not None and stored.status == "validated"
    assert stored.media_origin == "telegram_native"
    assert stored.media_metadata["duration_seconds"] == 8.5
    assert stored.validation_evidence["full_decode"] is True
    assert projection is not None and projection.submission_id == result.submission_id
    assert handoff is not None and handoff.consumed
    assert handoff.submission_id == result.submission_id
    assert issued.token not in str(stored.provenance)
    async with database.session_factory() as session:
        stored_digest = await session.scalar(select(MediaHandoffRequestModel.token_digest))
    assert stored_digest != issued.token
    assert stored_digest == hashlib.sha256(issued.token.encode("ascii")).hexdigest()

    with pytest.raises(SubmissionError) as replay:
        await service.submit(
            SubmissionRequest(media=media, selected_thread_id=thread.id, handoff=claim)
        )
    assert replay.value.code == "handoff_invalid"
    reconciled = await service.reconcile_handoff(claim)
    assert reconciled is not None
    assert reconciled.disposition == "existing"
    assert reconciled.submission_id == result.submission_id


@pytest.mark.parametrize(
    "claim_binding,media_chat",
    [
        (HandoffBinding(actor_id=101, conversation_chat_id=200), 200),
        (HandoffBinding(actor_id=100, conversation_chat_id=201), 201),
        (HandoffBinding(actor_id=100, conversation_chat_id=200, operation="other"), 200),
    ],
)
async def test_handoff_rejects_wrong_actor_conversation_or_operation(
    database, claim_binding, media_chat
):
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    expected = HandoffBinding(actor_id=100, conversation_chat_id=200)
    thread = await create_thread(database, SourceIdentity("telegram", "source-chat"))
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({"wrong-binding": unresolved()}),
        clock=lambda: now,
        token_factory=lambda: "B" * 43,
    )
    issued = await service.issue_handoff(expected)
    media = telegram_media("wrong-binding", chat_id=media_chat)

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            SubmissionRequest(
                media=media,
                selected_thread_id=thread.id,
                handoff=HandoffClaim(issued.token, claim_binding),
            )
        )

    assert error.value.code == "handoff_invalid"
    async with database.unit_of_work() as uow:
        assert await uow.submissions.get_by_source_media("telegram", "wrong-binding") is None


async def test_expired_handoff_rejects_media_without_partial_state(database):
    current = [datetime(2026, 10, 17, 10, tzinfo=UTC)]
    binding = HandoffBinding(actor_id=100, conversation_chat_id=200)
    thread = await create_thread(database, SourceIdentity("telegram", "source-chat"))
    media = telegram_media("expired")
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: unresolved()}),
        clock=lambda: current[0],
        token_factory=lambda: "C" * 43,
    )
    issued = await service.issue_handoff(binding, ttl_seconds=30)
    current[0] += timedelta(seconds=31)

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            SubmissionRequest(
                media=media,
                selected_thread_id=thread.id,
                handoff=HandoffClaim(issued.token, binding),
            )
        )

    assert error.value.code == "handoff_invalid"
    async with database.unit_of_work() as uow:
        assert await uow.submissions.get_by_source_media("telegram", media.source_media_id) is None


async def test_commit_failure_leaves_handoff_retryable_and_no_submission(database):
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    binding = HandoffBinding(actor_id=100, conversation_chat_id=200)
    thread = await create_thread(database, SourceIdentity("telegram", "source-chat"))
    media = telegram_media("commit-retry")
    service = SubmissionService(
        database.unit_of_work,
        MappingResolver({media.source_media_id: unresolved()}),
        clock=lambda: now,
        token_factory=lambda: "D" * 43,
    )
    issued = await service.issue_handoff(binding)
    claim = HandoffClaim(issued.token, binding)
    request = SubmissionRequest(media=media, selected_thread_id=thread.id, handoff=claim)

    def fail_commit(_session):
        raise RuntimeError("simulated commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(SubmissionError) as error:
            await service.submit(request)
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert error.value.code == "submission_persistence"
    assert await service.reconcile_handoff(claim) is None
    async with database.unit_of_work() as uow:
        assert await uow.submissions.get_by_source_media("telegram", media.source_media_id) is None

    retried = await service.submit(request)
    assert retried.disposition == "created"
    reconciled = await service.reconcile_handoff(claim)
    assert reconciled is not None and reconciled.submission_id == retried.submission_id


async def test_repository_handoff_consumption_is_compare_and_set(database):
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    digest = "e" * 64
    async with database.unit_of_work() as uow:
        handoff = await uow.handoffs.create(
            token_digest=digest,
            actor_id=100,
            conversation_chat_id=200,
            operation="telegram_submission",
            expires_at=now + timedelta(minutes=5),
        )
        first = await uow.submissions.create(
            source_provider="telegram", source_media_id="cas-first"
        )
        second = await uow.submissions.create(
            source_provider="telegram", source_media_id="cas-second"
        )

    async with database.unit_of_work() as uow:
        assert await uow.handoffs.consume(
            handoff_id=handoff.id, submission_id=first.id, consumed_at=now
        )
    async with database.unit_of_work() as uow:
        assert not await uow.handoffs.consume(
            handoff_id=handoff.id, submission_id=second.id, consumed_at=now
        )
        stored = await uow.handoffs.get_bound(
            token_digest=digest,
            actor_id=100,
            conversation_chat_id=200,
            operation="telegram_submission",
        )
    assert stored is not None and stored.submission_id == first.id
