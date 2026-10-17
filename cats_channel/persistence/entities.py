"""Persistence-facing records with no SQLAlchemy or Telegram transport dependency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MessagePurpose = Literal["destination", "private", "moderation"]


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


@dataclass(frozen=True)
class SourceIdentity:
    """Stable source key plus a complete current display-metadata snapshot.

    Null display fields represent absent metadata, not a partial-update request.
    """

    provider: str
    channel_id: str
    channel_name: str | None = None
    channel_username: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _required(self.provider, "provider").lower())
        object.__setattr__(self, "channel_id", _required(self.channel_id, "channel_id"))


@dataclass(frozen=True)
class CatVideoSubmission:
    id: str
    source_provider: str
    source_media_id: str
    source_channel_id: str | None
    thread_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CatThread:
    id: str
    source: SourceIdentity
    root_post_id: str | None
    tail_post_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CatPost:
    id: str
    submission_id: str
    thread_id: str
    parent_post_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class TelegramMessageRef:
    chat_id: int
    message_id: int

    def __post_init__(self) -> None:
        if self.chat_id == 0:
            raise ValueError("chat_id must not be zero")
        if self.message_id <= 0:
            raise ValueError("message_id must be positive")


@dataclass(frozen=True)
class TelegramProjection:
    id: str
    purpose: MessagePurpose
    reference: TelegramMessageRef
    post_id: str | None
    submission_id: str | None
    created_at: datetime
