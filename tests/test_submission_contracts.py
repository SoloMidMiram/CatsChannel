from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cats_channel.errors import error_record
from cats_channel.models import LibraryItem
from cats_channel.persistence.entities import (
    CatThread,
    CatVideoSubmission,
    SourceIdentity,
    TelegramMessageRef,
)
from cats_channel.submissions import (
    HandoffBinding,
    LibraryManifestSourceResolver,
    MediaValidationEvidence,
    SubmissionError,
    SubmissionRequest,
    SubmissionService,
    SubmissionVideoMetadata,
    ValidatedTelegramMedia,
    local_media_from_library_item,
)


def library_item(tmp_path: Path, *, backend: str = "yt_dlp") -> LibraryItem:
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"validated")
    receipt = None
    if backend == "telegram_bot":
        receipt = {
            "backend": "telegram_bot",
            "bot_id": 100,
            "request_message_id": 10,
            "response_message_id": 11,
            "source_identity_verified": False,
            "correlation": "reply",
        }
    return LibraryItem(
        status="stored",
        item_path="library/youtube/abcdefghijk",
        media_path=media_path,
        manifest={
            "schema_version": 2,
            "downloaded_at": "2026-10-17T10:00:00+00:00",
            "source": {"provider": "youtube", "video_id": "abcdefghijk"},
            "metadata": {
                "title": "Cat",
                "channel_id": "UC-stable",
                "channel": "Cats",
                "uploader_id": "@cats",
            },
            "playback_validation": {
                "status": "passed",
                "full_decode": "passed",
                "duration_seconds": 12.5,
                "format_name": "mov,mp4",
                "video_stream_count": 1,
                "audio_stream_count": 1,
                "video_codec": "h264",
                "width": 360,
                "height": 640,
                "audio_codecs": ["aac"],
            },
            "file": {
                "name": "media.mp4",
                "size_bytes": len(b"validated"),
                "sha256": "a" * 64,
            },
            "acquisition": {"backend": backend, "receipt": receipt},
        },
    )


async def test_library_adapter_exposes_only_explicit_validated_evidence(tmp_path):
    media = local_media_from_library_item(library_item(tmp_path))

    assert media.source_provider == "youtube"
    assert media.source_media_id == "abcdefghijk"
    assert media.metadata.duration_seconds == 12.5
    assert media.validation.full_decode is True
    assert media.validation.video_stream_count == 1
    assert media.source_metadata.channel_id == "UC-stable"
    assert "canonical_url" not in media.provenance

    resolved = await LibraryManifestSourceResolver().resolve(media)
    assert resolved.status == "verified"
    assert resolved.identity is not None
    assert resolved.identity.channel_id == "UC-stable"


async def test_third_party_downloader_identity_remains_unresolved(tmp_path):
    media = local_media_from_library_item(library_item(tmp_path, backend="telegram_bot"))

    resolved = await LibraryManifestSourceResolver().resolve(media)

    assert resolved.status == "unresolved"
    assert resolved.identity is None
    assert media.provenance["receipt"]["source_identity_verified"] is False


@pytest.mark.parametrize(
    "manifest_change",
    [
        lambda manifest: manifest.pop("playback_validation"),
        lambda manifest: manifest["playback_validation"].update(full_decode="failed"),
        lambda manifest: manifest["file"].update(sha256="not-a-digest"),
    ],
)
def test_library_adapter_rejects_missing_or_invalid_validation(tmp_path, manifest_change):
    item = library_item(tmp_path)
    manifest_change(item.manifest)

    with pytest.raises(SubmissionError) as error:
        local_media_from_library_item(item)

    assert error.value.code == "submission_media_invalid"


def test_telegram_native_contract_requires_a_handoff():
    media = ValidatedTelegramMedia(
        source_provider="telegram",
        source_media_id="stable-file-unique-id",
        reference=TelegramMessageRef(chat_id=42, message_id=7),
        file_id="downloadable-file-id",
        file_unique_id="stable-file-unique-id",
        metadata=SubmissionVideoMetadata(title=None, duration_seconds=5),
        validation=MediaValidationEvidence(
            validator="test-validator",
            validated_at=datetime.now(UTC),
            size_bytes=100,
            duration_seconds=5,
            sha256=None,
            video_stream_count=1,
            audio_stream_count=0,
            full_decode=True,
        ),
    )

    with pytest.raises(SubmissionError) as error:
        SubmissionRequest(media=media)

    assert error.value.code == "handoff_invalid"
    assert HandoffBinding(actor_id=1, conversation_chat_id=42).operation == ("telegram_submission")


async def test_submission_service_uses_fake_repository_contracts_without_sqlalchemy(tmp_path):
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    media = local_media_from_library_item(library_item(tmp_path))
    identity = SourceIdentity("youtube", "UC-stable", "Cats", "@cats")
    thread = CatThread("thread-id", identity, None, None, 0, now, now)
    submission = CatVideoSubmission(
        id="submission-id",
        source_provider="youtube",
        source_media_id="abcdefghijk",
        source_channel_id="UC-stable",
        source_channel_name="Cats",
        source_channel_username="@cats",
        source_identity_status="verified",
        thread_id=thread.id,
        status="validated",
        media_origin="local_library",
        media_metadata=media.metadata.to_record(),
        validation_evidence=media.validation.to_record(),
        provenance={},
        created_at=now,
        updated_at=now,
    )
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.threads.get_or_create = AsyncMock(return_value=thread)
    uow.submissions.create = AsyncMock(return_value=submission)
    resolver = AsyncMock()
    resolver.resolve.return_value = await LibraryManifestSourceResolver().resolve(media)
    service = SubmissionService(lambda: uow, resolver)

    result = await service.submit(SubmissionRequest(media))

    assert result.submission_id == submission.id
    uow.threads.get_or_create.assert_awaited_once_with(identity)
    uow.submissions.create.assert_awaited_once()
    uow.__aexit__.assert_awaited_once()


async def test_submission_service_preserves_resolver_cancellation(tmp_path):
    media = local_media_from_library_item(library_item(tmp_path))
    resolver = AsyncMock()
    resolver.resolve.side_effect = asyncio.CancelledError
    unit_of_work = MagicMock()
    service = SubmissionService(unit_of_work, resolver)

    with pytest.raises(asyncio.CancelledError):
        await service.submit(SubmissionRequest(media))

    unit_of_work.assert_not_called()


@pytest.mark.parametrize(
    "code",
    [
        "submission_media_invalid",
        "source_identity_unresolved",
        "source_identity_conflict",
        "source_selection_invalid",
        "duplicate_media",
        "handoff_invalid",
        "submission_persistence",
    ],
)
def test_submission_errors_have_safe_bot_facing_policies(code):
    record = error_record(code)

    assert record["code"] == code
    assert record["message"]
    assert record["action"]
    assert record["retry_policy"]
    assert "token" not in str(record).lower()
