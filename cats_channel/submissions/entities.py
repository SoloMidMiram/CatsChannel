"""Transport- and ORM-independent submission input and result contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, TypeAlias

from ..persistence.entities import SourceIdentity, TelegramMessageRef
from ..reply_tokens import ReplyTarget
from .errors import SubmissionError

SourceIdentityStatus = Literal["verified", "user_selected", "unresolved"]
SubmissionLifecycle = Literal["validated"]
MediaOrigin = Literal["local_library", "telegram_native"]

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True)
class SourceMetadata:
    """Source fields reported by an adapter; not proof of stable identity."""

    channel_id: str | None = None
    channel_name: str | None = None
    channel_username: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel_id", _optional(self.channel_id))
        object.__setattr__(self, "channel_name", _optional(self.channel_name))
        object.__setattr__(self, "channel_username", _optional(self.channel_username))


@dataclass(frozen=True)
class SubmissionVideoMetadata:
    title: str | None
    duration_seconds: float
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be finite and positive")
        for field_name in ("width", "height"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or value <= 0):
                raise ValueError(f"{field_name} must be positive")
        object.__setattr__(self, "title", _optional(self.title))
        object.__setattr__(self, "video_codec", _optional(self.video_codec))
        object.__setattr__(self, "audio_codec", _optional(self.audio_codec))
        object.__setattr__(self, "container", _optional(self.container))

    def to_record(self) -> dict[str, object]:
        return {
            "title": self.title,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "container": self.container,
        }


@dataclass(frozen=True)
class MediaValidationEvidence:
    validator: str
    validated_at: datetime
    size_bytes: int
    duration_seconds: float
    sha256: str | None
    video_stream_count: int
    audio_stream_count: int
    full_decode: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "validator", _required(self.validator, "validator"))
        if self.validated_at.tzinfo is None or self.validated_at.utcoffset() is None:
            raise ValueError("validated_at must be timezone-aware")
        if isinstance(self.size_bytes, bool) or self.size_bytes <= 0:
            raise ValueError("size_bytes must be positive")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be finite and positive")
        if self.sha256 is not None and not _SHA256.fullmatch(self.sha256):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        if self.video_stream_count < 1 or self.audio_stream_count < 0:
            raise ValueError("validated media must contain a video stream")
        if self.full_decode is not True:
            raise ValueError("validated media must pass a full decode")

    def to_record(self) -> dict[str, object]:
        return {
            "validator": self.validator,
            "validated_at": self.validated_at.astimezone(UTC).isoformat(),
            "size_bytes": self.size_bytes,
            "duration_seconds": self.duration_seconds,
            "sha256": self.sha256,
            "video_stream_count": self.video_stream_count,
            "audio_stream_count": self.audio_stream_count,
            "full_decode": self.full_decode,
        }


@dataclass(frozen=True)
class ValidatedLocalMedia:
    source_provider: str
    source_media_id: str
    item_path: str
    backend: str
    metadata: SubmissionVideoMetadata
    validation: MediaValidationEvidence
    source_metadata: SourceMetadata = field(default_factory=SourceMetadata)
    provenance: dict[str, object] = field(default_factory=dict)
    origin: MediaOrigin = field(default="local_library", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, SubmissionVideoMetadata) or not isinstance(
            self.validation, MediaValidationEvidence
        ):
            raise SubmissionError("submission_media_invalid")
        object.__setattr__(
            self, "source_provider", _required(self.source_provider, "source_provider").lower()
        )
        object.__setattr__(
            self, "source_media_id", _required(self.source_media_id, "source_media_id")
        )
        object.__setattr__(self, "item_path", _required(self.item_path, "item_path"))
        object.__setattr__(self, "backend", _required(self.backend, "backend"))


@dataclass(frozen=True)
class ValidatedTelegramMedia:
    source_provider: str
    source_media_id: str
    reference: TelegramMessageRef
    file_id: str
    file_unique_id: str
    metadata: SubmissionVideoMetadata
    validation: MediaValidationEvidence
    source_metadata: SourceMetadata = field(default_factory=SourceMetadata)
    provenance: dict[str, object] = field(default_factory=dict)
    origin: MediaOrigin = field(default="telegram_native", init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.metadata, SubmissionVideoMetadata)
            or not isinstance(self.validation, MediaValidationEvidence)
            or not isinstance(self.reference, TelegramMessageRef)
        ):
            raise SubmissionError("submission_media_invalid")
        object.__setattr__(
            self, "source_provider", _required(self.source_provider, "source_provider").lower()
        )
        object.__setattr__(
            self, "source_media_id", _required(self.source_media_id, "source_media_id")
        )
        object.__setattr__(self, "file_id", _required(self.file_id, "file_id"))
        object.__setattr__(self, "file_unique_id", _required(self.file_unique_id, "file_unique_id"))
        # Telegram delivery coordinates and bot-specific file IDs are projections.
        # Its provider-scoped media key is always the stable file_unique_id.
        if self.source_provider != "telegram" or self.source_media_id != self.file_unique_id:
            raise SubmissionError("submission_media_invalid")


SubmissionMedia: TypeAlias = ValidatedLocalMedia | ValidatedTelegramMedia


@dataclass(frozen=True)
class ResolvedSourceIdentity:
    status: Literal["verified", "unresolved"]
    identity: SourceIdentity | None
    method: str
    evidence: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _required(self.method, "method"))
        if self.status == "verified" and self.identity is None:
            raise ValueError("verified source identity requires a stable identity")
        if self.status == "unresolved" and self.identity is not None:
            raise ValueError("unresolved source identity cannot contain an identity")


@dataclass(frozen=True)
class HandoffBinding:
    actor_id: int
    conversation_chat_id: int
    operation: str = "telegram_submission"

    def __post_init__(self) -> None:
        if self.actor_id <= 0:
            raise ValueError("actor_id must be positive")
        if self.conversation_chat_id == 0:
            raise ValueError("conversation_chat_id must not be zero")
        object.__setattr__(self, "operation", _required(self.operation, "operation"))


@dataclass(frozen=True)
class HandoffClaim:
    token: str
    binding: HandoffBinding

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", _required(self.token, "token"))


@dataclass(frozen=True)
class SubmissionRequest:
    media: SubmissionMedia
    selected_thread_id: str | None = None
    handoff: HandoffClaim | None = None
    authorized_reply_target: ReplyTarget | None = None
    inbound_reference: TelegramMessageRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.media, (ValidatedLocalMedia, ValidatedTelegramMedia)):
            raise SubmissionError("submission_media_invalid")
        object.__setattr__(self, "selected_thread_id", _optional(self.selected_thread_id))
        if self.authorized_reply_target is not None and not isinstance(
            self.authorized_reply_target, ReplyTarget
        ):
            raise SubmissionError("source_selection_invalid")
        if self.selected_thread_id is not None and self.authorized_reply_target is not None:
            raise SubmissionError("source_selection_invalid")
        if self.inbound_reference is not None and not isinstance(
            self.inbound_reference, TelegramMessageRef
        ):
            raise SubmissionError("handoff_invalid")
        if isinstance(self.media, ValidatedTelegramMedia):
            if self.inbound_reference is None:
                object.__setattr__(self, "inbound_reference", self.media.reference)
            elif self.inbound_reference != self.media.reference:
                raise SubmissionError("handoff_invalid")
        if isinstance(self.media, ValidatedTelegramMedia) and self.handoff is None:
            raise SubmissionError("handoff_invalid")


@dataclass(frozen=True)
class IssuedHandoff:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class SubmissionResult:
    disposition: Literal["created", "existing"]
    submission_id: str
    thread_id: str
    lifecycle: SubmissionLifecycle
    source_identity_status: SourceIdentityStatus
