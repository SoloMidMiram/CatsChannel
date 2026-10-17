"""Immutable durable intent and token records plus placement results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

PlacementMode = Literal["normal_append", "interactive_reply"]


@dataclass(frozen=True)
class PostIntent:
    id: str
    submission_id: str
    thread_id: str
    mode: PlacementMode
    selected_parent_post_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReplyEntryToken:
    token_digest: str = field(repr=False)
    post_id: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class IssuedReplyToken:
    token: str = field(repr=False)
    post_id: str
    expires_at: datetime | None


@dataclass(frozen=True)
class PlacedPost:
    post_id: str
    thread_id: str
    parent_post_id: str | None
    advances_tail: bool
