"""Reviewed provenance schemas shared by application and persistence boundaries."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Backend = Literal["yt_dlp", "telegram_bot", "telegram_native"]
ResolutionMethod = Literal["direct_extractor_metadata", "identity_not_verified", "adapter_verified"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AcquisitionReceipt(_Record):
    backend: Literal["telegram_bot"]
    bot_id: int = Field(gt=0)
    request_message_id: int = Field(gt=0)
    response_message_id: int = Field(gt=0)
    source_identity_verified: Literal[False]
    correlation: Literal["reply", "serialized_conversation"]


class LocalMediaProvenance(_Record):
    library_item_path: str | None = Field(
        default=None, pattern=r"^library/[a-z][a-z0-9_]*/[A-Za-z0-9_-]{1,128}$"
    )
    acquisition_backend: Backend | None = None
    downloaded_at: str | None = None
    receipt: AcquisitionReceipt | None = None

    @field_validator("downloaded_at")
    @classmethod
    def _timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("downloaded_at must be timezone-aware")
        return timestamp.astimezone(UTC).isoformat()


class TelegramMediaProvenance(_Record):
    adapter: Literal["telegram_native"] | None = None


class ResolutionEvidence(_Record):
    adapter: Backend | None = None
    stable_channel_id: bool | None = None
    trusted: bool | None = None


class SourceResolutionProvenance(_Record):
    status: Literal["verified", "unresolved"]
    method: ResolutionMethod
    evidence: ResolutionEvidence


class TelegramFileProvenance(_Record):
    file_id: str = Field(min_length=1, max_length=1024)
    file_unique_id: str = Field(min_length=1, max_length=255)


class LocalSubmissionProvenance(_Record):
    media: LocalMediaProvenance
    source_resolution: SourceResolutionProvenance


class TelegramSubmissionProvenance(_Record):
    media: TelegramMediaProvenance
    source_resolution: SourceResolutionProvenance
    telegram: TelegramFileProvenance


def _record(schema: type[_Record], value: object) -> dict[str, object]:
    try:
        return schema.model_validate(value).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        # Do not echo rejected credentials/private payloads in diagnostics.
        raise ValueError("Invalid provenance schema") from None


def media_provenance_record(value: object, origin: str) -> dict[str, object]:
    schema = LocalMediaProvenance if origin == "local_library" else TelegramMediaProvenance
    return _record(schema, value)


def source_resolution_record(value: object) -> dict[str, object]:
    return _record(SourceResolutionProvenance, value)


def submission_provenance_record(value: object, origin: str) -> dict[str, object]:
    # Legacy rows and repository-only pending records have no provenance yet.
    if value is None or value == {}:
        return {}
    if origin == "local_library":
        schema = LocalSubmissionProvenance
    elif origin == "telegram_native":
        schema = TelegramSubmissionProvenance
    else:
        raise ValueError("Legacy provenance must be empty")
    return _record(schema, value)
