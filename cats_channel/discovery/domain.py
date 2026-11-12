"""Immutable metadata-only contracts and strict input normalization."""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit


class Status(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    UNAVAILABLE = "unavailable"
    AMBIGUOUS = "ambiguous"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    CONFIGURATION_ERROR = "configuration_error"
    INVALID_INPUT = "invalid_input"


class WatchlistError(Exception):
    """Sanitized application error code."""


def normalize(value: str) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("invalid_input")
    value = value.strip()
    if any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("invalid_input")
    if "://" in value:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.netloc not in {"youtube.com", "www.youtube.com"}
            or url.query
            or url.fragment
            or "?" in value
            or "#" in value
        ):
            raise ValueError("invalid_input")
        path = url.path.removesuffix("/").removesuffix("/shorts")
        if not re.fullmatch(
            r"/(?:channel/UC[A-Za-z0-9_-]{22}|@[A-Za-z0-9][A-Za-z0-9_.-]{2,29})", path
        ):
            raise ValueError("invalid_input")
        value = path.removeprefix("/channel/") if path.startswith("/channel/") else path[1:]
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", value):
        return value
    if re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9_.-]{2,29}", value):
        return value.lower()
    raise ValueError("invalid_input")


@dataclass(frozen=True)
class ScanPolicy:
    page_budget: int = 30
    lookback_days: int = 30

    def __post_init__(self):
        if any(
            type(v) is not int or not 1 <= v <= 10000
            for v in (self.page_budget, self.lookback_days)
        ):
            raise ValueError("invalid_scan_policy")


@dataclass(frozen=True)
class Operator:
    name: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.name):
            raise ValueError("invalid_operator")


@dataclass(frozen=True)
class Resolution:
    status: Status
    channel_id: str | None = None
    handle: str | None = None
    display_name: str | None = None
    evidence: str = "none"
    retry_after_seconds: int | None = None
    uploads_playlist_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.status, Status):
            raise TypeError("invalid_status")
        if self.status == Status.RESOLVED:
            if not self.channel_id or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", self.channel_id):
                raise ValueError("invalid_channel_identity")
        elif self.channel_id is not None:
            raise ValueError("unexpected_channel_identity")
        if self.uploads_playlist_id is not None and (
            self.status != Status.RESOLVED
            or not isinstance(self.uploads_playlist_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.uploads_playlist_id)
        ):
            raise ValueError("invalid_uploads_playlist_id")
        if self.handle is not None and not re.fullmatch(
            r"@[A-Za-z0-9][A-Za-z0-9_.-]{2,29}", self.handle
        ):
            raise ValueError("invalid_handle")
        if self.display_name is not None and (
            len(self.display_name) > 255 or any(ord(c) < 32 for c in self.display_name)
        ):
            raise ValueError("invalid_display_name")
        if self.evidence not in {
            "none",
            "provider_channel_id",
            "provider_unavailable",
            "resolver_not_configured",
            "synthetic",
        }:
            raise ValueError("invalid_evidence")
        if self.retry_after_seconds is not None and (
            type(self.retry_after_seconds) is not int or not 0 <= self.retry_after_seconds <= 86400
        ):
            raise ValueError("invalid_retry_after")


@dataclass(frozen=True)
class Entry:
    id: str
    reference: str
    channel_id: str | None
    handle: str | None
    display_name: str | None
    enabled: bool
    retired: bool
    status: Status
    evidence: str
    retry_after_seconds: int | None
    last_resolved_at: datetime | None
    policy: ScanPolicy
    version: int
    created_at: datetime
    updated_at: datetime
    provider: str = "youtube"

    @property
    def canonical_url(self) -> str | None:
        return f"https://www.youtube.com/channel/{self.channel_id}" if self.channel_id else None


@dataclass(frozen=True)
class Registration:
    entry: Entry
    outcome: str


@dataclass(frozen=True)
class Change:
    operator: str
    operation: str
    status: Status
    handle: str | None
    evidence: str
    version: int
    enabled: bool
    retired: bool
    policy: ScanPolicy
    created_at: datetime


@dataclass(frozen=True)
class ProviderConfiguration:
    adapter: str
    timeout_seconds: int = 30
    request_budget: int = 30

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", self.adapter):
            raise ValueError("invalid_adapter")
        if not 1 <= self.timeout_seconds <= 300 or not 1 <= self.request_budget <= 10000:
            raise ValueError("invalid_provider_budget")


@dataclass(frozen=True)
class Candidate:
    channel_id: str
    video_id: str
    observed_at: datetime
    discovery_method: str
    title: str | None = None
    published_at: datetime | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    classification: str = "unknown"
    evidence: tuple[str, ...] = ()
    checkpoint_provenance: str | None = None
    provider: str = "youtube"

    def __post_init__(self):
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", self.channel_id):
            raise ValueError("invalid_channel_identity")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", self.video_id):
            raise ValueError("invalid_video_identity")
        if self.provider != "youtube" or self.classification not in {
            "unknown",
            "shorts_tab",
            "short_candidate",
            "not_short",
        }:
            raise ValueError("invalid_candidate")
        if self.title is not None and len(self.title) > 500:
            raise ValueError("invalid_title")
        if len(self.evidence) > 16 or any(len(v) > 128 for v in self.evidence):
            raise ValueError("invalid_evidence")
        if self.duration_seconds is not None and (
            not math.isfinite(self.duration_seconds) or self.duration_seconds < 0
        ):
            raise ValueError("invalid_duration")
        if any(
            v is not None and (type(v) is not int or not 1 <= v <= 65536)
            for v in (self.width, self.height)
        ):
            raise ValueError("invalid_geometry")
        if self.observed_at.tzinfo is None or (
            self.published_at is not None and self.published_at.tzinfo is None
        ):
            raise ValueError("timezone_required")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", self.discovery_method):
            raise ValueError("invalid_discovery_method")
        if self.checkpoint_provenance is not None and len(self.checkpoint_provenance) > 2048:
            raise ValueError("invalid_provenance")

    @property
    def canonical_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class PageResult:
    candidates: tuple[Candidate, ...]
    state: str
    next_cursor: str | None = None
    failure: Status | None = None
    retry_after_seconds: int | None = None

    def __post_init__(self):
        if self.state not in {"complete", "partial", "failed"}:
            raise ValueError("invalid_page_state")
        if self.next_cursor is not None and len(self.next_cursor) > 2048:
            raise ValueError("invalid_cursor")
        if len(self.candidates) > 10000:
            raise ValueError("page_too_large")
        if self.failure is not None and self.failure not in {
            Status.UNAVAILABLE,
            Status.AMBIGUOUS,
            Status.RATE_LIMITED,
            Status.TEMPORARY_FAILURE,
            Status.INVALID_INPUT,
        }:
            raise ValueError("invalid_page_failure")
        if self.retry_after_seconds is not None and (
            type(self.retry_after_seconds) is not int or not 0 <= self.retry_after_seconds <= 86400
        ):
            raise ValueError("invalid_retry_after")

    @property
    def checkpoint_may_advance(self) -> bool:
        return self.state == "complete" and self.failure is None
