"""Transport-independent contracts for authenticated bot submission intake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..reply_chains.entities import PlacementMode
from ..reply_tokens import ReplyTarget, internal_id


@dataclass(frozen=True)
class IntakePlacement:
    mode: PlacementMode
    thread_id: str | None = None
    selected_parent_post_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode == "normal_append":
            if self.selected_parent_post_id is not None:
                raise ValueError("Normal intake cannot select an exact parent")
            if self.thread_id is not None:
                internal_id(self.thread_id)
            return
        if self.mode != "interactive_reply" or self.thread_id is None:
            raise ValueError("Interactive intake requires a target")
        internal_id(self.thread_id)
        if self.selected_parent_post_id is None:
            raise ValueError("Interactive intake requires an exact parent")
        internal_id(self.selected_parent_post_id)

    @classmethod
    def normal(cls, thread_id: str | None = None) -> IntakePlacement:
        return cls("normal_append", thread_id=thread_id)

    @classmethod
    def interactive(cls, target: ReplyTarget) -> IntakePlacement:
        if not isinstance(target, ReplyTarget):
            raise TypeError("Expected an authorized reply target")
        return cls(
            "interactive_reply",
            thread_id=target.thread_id,
            selected_parent_post_id=target.post_id,
        )


@dataclass(frozen=True)
class IntakeResult:
    disposition: Literal["created", "existing", "recovered"]
    submission_id: str
    intent_id: str
    thread_id: str
    mode: PlacementMode
    lifecycle: Literal["pending"] = "pending"


@dataclass(frozen=True)
class SourceOption:
    thread_id: str
    provider: str
    display_name: str

    def __post_init__(self) -> None:
        internal_id(self.thread_id)
        if not self.provider or not self.display_name:
            raise ValueError("Source option fields must not be empty")
