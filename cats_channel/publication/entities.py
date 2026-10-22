"""Transport-independent delivery state and immutable snapshots."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

State = Literal["pending", "blocked", "sending", "confirmed", "failed", "unknown"]
MarkupState = Literal["pending", "installed", "failed"]
TRANSITIONS = {
    "pending": {"blocked", "sending"},
    "blocked": {"pending"},
    "sending": {"confirmed", "failed", "unknown"},
    "unknown": {"confirmed", "failed"},
    "failed": {"pending"},
    "confirmed": set(),
}


def validate_transition(before: State, after: State) -> None:
    from .errors import PublicationError

    if after not in TRANSITIONS.get(before, set()):
        raise PublicationError("publication_transition_invalid")


@dataclass(frozen=True)
class Publication:
    id: str
    post_id: str
    destination_chat_id: int
    state: State
    version: int
    current_attempt_id: str | None
    error_category: str | None
    markup_status: MarkupState
    markup_token_digest: str | None = field(repr=False)
    navigation_post_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Attempt:
    id: str
    publication_id: str
    number: int
    claim_token: str = field(repr=False)
    started_at: datetime
    completed_at: datetime | None = None
    outcome: str | None = None
    error_category: str | None = None
    recovery: str | None = None
