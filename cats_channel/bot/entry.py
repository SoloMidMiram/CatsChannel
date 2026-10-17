"""Opaque public reply links and internal-ID transport conventions."""

from __future__ import annotations

import re
from typing import Literal, Protocol

from aiogram.filters.callback_data import CallbackData
from pydantic import field_validator

from ..reply_tokens import (
    EntryContractError,
    ReplyTarget,
    internal_id,
    new_reply_token,
    validate_reply_token,
)

__all__ = [
    "EntryContractError",
    "ModerationCallback",
    "ReplyTarget",
    "ReplyTargetResolver",
    "UnavailableReplyTargetResolver",
    "build_reply_link",
    "internal_id",
    "new_reply_token",
    "parse_reply_payload",
    "validate_reply_token",
]

_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")
REPLY_PREFIX = "catreply_"


def parse_reply_payload(payload: str) -> str:
    if not isinstance(payload, str) or not payload.startswith(REPLY_PREFIX):
        raise EntryContractError()
    return validate_reply_token(payload[len(REPLY_PREFIX) :])


def build_reply_link(bot_username: str, token: str) -> str:
    username = bot_username.removeprefix("@")
    if not _USERNAME.fullmatch(username):
        raise EntryContractError()
    return f"https://t.me/{username}?start={REPLY_PREFIX}{validate_reply_token(token)}"


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
