"""Async persistence boundaries for CatsChannel domain state.

ORM-independent records and protocols remain importable without the optional
persistence dependencies. ``Database`` is loaded only when requested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .contracts import (
    HandoffRepository,
    PersistenceUnitOfWork,
    ProjectionRepository,
    SubmissionRepository,
    ThreadRepository,
)
from .entities import (
    CatPost,
    CatThread,
    CatVideoSubmission,
    HandoffRequest,
    SourceIdentity,
    TelegramMessageRef,
    TelegramProjection,
)
from .errors import (
    ConcurrentThreadUpdateError,
    CrossThreadParentError,
    DuplicateHandoffTokenError,
    DuplicatePostSubmissionError,
    DuplicateSourceMediaError,
    DuplicateTelegramMessageError,
    InvalidThreadStateError,
    MissingParentError,
    PersistenceError,
    PostNotFoundError,
    SubmissionNotFoundError,
    ThreadNotFoundError,
)

if TYPE_CHECKING:
    from .database import Database


def __getattr__(name: str) -> Any:
    if name == "Database":
        from .database import Database

        return Database
    raise AttributeError(name)


__all__ = [
    "CatPost",
    "CatThread",
    "CatVideoSubmission",
    "ConcurrentThreadUpdateError",
    "CrossThreadParentError",
    "Database",
    "DuplicateHandoffTokenError",
    "DuplicatePostSubmissionError",
    "DuplicateSourceMediaError",
    "DuplicateTelegramMessageError",
    "HandoffRepository",
    "HandoffRequest",
    "InvalidThreadStateError",
    "MissingParentError",
    "PersistenceError",
    "PersistenceUnitOfWork",
    "PostNotFoundError",
    "ProjectionRepository",
    "SourceIdentity",
    "SubmissionNotFoundError",
    "SubmissionRepository",
    "TelegramMessageRef",
    "TelegramProjection",
    "ThreadNotFoundError",
    "ThreadRepository",
]
