"""Adapt a validated media-library item into the submission input contract."""

from __future__ import annotations

from datetime import UTC, datetime

from ..models import LibraryItem
from .entities import (
    MediaValidationEvidence,
    SourceMetadata,
    SubmissionVideoMetadata,
    ValidatedLocalMedia,
)
from .errors import SubmissionError


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SubmissionError("submission_media_invalid")
    return value


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubmissionError("submission_media_invalid")
    return float(value)


def _integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise SubmissionError("submission_media_invalid")
    return int(value)


def _validated_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise SubmissionError("submission_media_invalid")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise SubmissionError("submission_media_invalid") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise SubmissionError("submission_media_invalid")
    return result.astimezone(UTC)


def local_media_from_library_item(item: LibraryItem) -> ValidatedLocalMedia:
    """Require the curated manifest evidence produced by ``MediaService``."""
    try:
        if not item.media_path.is_file():
            raise SubmissionError("submission_media_invalid")
        manifest = _mapping(item.manifest)
        source = _mapping(manifest.get("source"))
        metadata = _mapping(manifest.get("metadata"))
        playback = _mapping(manifest.get("playback_validation"))
        file_record = _mapping(manifest.get("file"))
        acquisition = _mapping(manifest.get("acquisition"))
        if playback.get("status") != "passed" or playback.get("full_decode") != "passed":
            raise SubmissionError("submission_media_invalid")
        provider = _string(source.get("provider"))
        media_id = _string(source.get("video_id"))
        backend = _string(acquisition.get("backend"))
        if provider is None or media_id is None or backend is None:
            raise SubmissionError("submission_media_invalid")
        audio_codecs = playback.get("audio_codecs")
        audio_codec = (
            audio_codecs[0]
            if isinstance(audio_codecs, list) and audio_codecs and isinstance(audio_codecs[0], str)
            else None
        )
        video_metadata = SubmissionVideoMetadata(
            title=_string(metadata.get("title")),
            duration_seconds=_number(playback.get("duration_seconds")),
            width=_integer(playback.get("width")),
            height=_integer(playback.get("height")),
            video_codec=_string(playback.get("video_codec")),
            audio_codec=audio_codec,
            container=_string(playback.get("format_name")),
        )
        validation = MediaValidationEvidence(
            validator="ffprobe+ffmpeg",
            validated_at=_validated_at(manifest.get("downloaded_at")),
            size_bytes=_integer(file_record.get("size_bytes")) or 0,
            duration_seconds=video_metadata.duration_seconds,
            sha256=_string(file_record.get("sha256")),
            video_stream_count=_integer(playback.get("video_stream_count")) or 0,
            audio_stream_count=_integer(playback.get("audio_stream_count")) or 0,
            full_decode=True,
        )
        receipt = acquisition.get("receipt")
        receipt_record: dict[str, object] | None = None
        if isinstance(receipt, dict):
            receipt_record = {
                key: receipt[key]
                for key in (
                    "backend",
                    "bot_id",
                    "request_message_id",
                    "response_message_id",
                    "source_identity_verified",
                    "correlation",
                )
                if key in receipt and isinstance(receipt[key], (str, int, bool))
            }
        return ValidatedLocalMedia(
            source_provider=provider,
            source_media_id=media_id,
            item_path=item.item_path,
            backend=backend,
            metadata=video_metadata,
            validation=validation,
            source_metadata=SourceMetadata(
                channel_id=_string(metadata.get("channel_id")),
                channel_name=_string(metadata.get("channel")),
                channel_username=_string(metadata.get("uploader_id")),
            ),
            provenance={
                "library_item_path": item.item_path,
                "acquisition_backend": backend,
                "downloaded_at": validation.validated_at.isoformat(),
                "receipt": receipt_record,
            },
        )
    except SubmissionError:
        raise
    except (TypeError, ValueError):
        raise SubmissionError("submission_media_invalid") from None
