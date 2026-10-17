"""Transport-independent opaque reply-token and internal identity syntax."""

import base64
import re
import secrets
from dataclasses import dataclass
from uuid import UUID


class EntryContractError(ValueError):
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
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise EntryContractError()
    raw = base64.urlsafe_b64decode(token + "=")
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != token:
        raise EntryContractError()
    return token


def new_reply_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ReplyTarget:
    post_id: str
    thread_id: str

    def __post_init__(self) -> None:
        internal_id(self.post_id)
        internal_id(self.thread_id)
