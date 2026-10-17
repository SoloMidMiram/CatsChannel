"""Opaque public reply links and internal-ID transport conventions."""

from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from aiogram.filters.callback_data import CallbackData
from pydantic import field_validator

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")
REPLY_PREFIX = "catreply_"


class EntryContractError(ValueError):
    """Safe rejection; never include token, callback, or message contents."""

    def __init__(self) -> None:
        super().__init__("Invalid reply entry")


def internal_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise EntryContractError() from None
    if parsed.version != 4 or str(parsed) != value:
        raise EntryContractError()
    return value


def validate_reply_token(token: str) -> str:
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise EntryContractError()
    raw = base64.urlsafe_b64decode(token + "=")
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != token:
        raise EntryContractError()
    return token


def new_reply_token() -> str:
    return secrets.token_urlsafe(32)


def parse_reply_payload(payload: str) -> str:
    if not isinstance(payload, str) or not payload.startswith(REPLY_PREFIX):
        raise EntryContractError()
    return validate_reply_token(payload[len(REPLY_PREFIX) :])


def build_reply_link(bot_username: str, token: str) -> str:
    username = bot_username.removeprefix("@")
    if not _USERNAME.fullmatch(username):
        raise EntryContractError()
    return f"https://t.me/{username}?start={REPLY_PREFIX}{validate_reply_token(token)}"


@dataclass(frozen=True)
class ReplyTarget:
    post_id: str
    thread_id: str

    def __post_init__(self) -> None:
        internal_id(self.post_id)
        internal_id(self.thread_id)


class ReplyTargetResolver(Protocol):
    async def resolve(self, token: str, *, actor_id: int) -> ReplyTarget | None:
        """Return an authorized internal target, or None for any unavailable token."""
        ...


class UnavailableReplyTargetResolver:
    """Fail closed until the reply-domain owner supplies token resolution."""

    async def resolve(self, token: str, *, actor_id: int) -> ReplyTarget | None:
        return None


class ModerationCallback(CallbackData, prefix="catmod"):
    """Wire convention only; no moderation action is executed here."""

    action: Literal["approve", "reject"]
    submission_id: str

    @field_validator("submission_id")
    @classmethod
    def _internal_submission(cls, value: str) -> str:
        return internal_id(value)
