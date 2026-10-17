"""Async persistence boundaries for CatsChannel domain state."""

from .contracts import (
    PersistenceUnitOfWork,
    ProjectionRepository,
    SubmissionRepository,
    ThreadRepository,
)
from .database import Database
from .entities import (
    CatPost,
    CatThread,
    CatVideoSubmission,
    SourceIdentity,
    TelegramMessageRef,
    TelegramProjection,
)
from .errors import (
    ConcurrentThreadUpdateError,
    CrossThreadParentError,
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

__all__ = [
    "CatPost",
    "CatThread",
    "CatVideoSubmission",
    "ConcurrentThreadUpdateError",
    "CrossThreadParentError",
    "Database",
    "DuplicatePostSubmissionError",
    "DuplicateSourceMediaError",
    "DuplicateTelegramMessageError",
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
