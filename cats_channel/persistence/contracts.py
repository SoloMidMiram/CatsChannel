"""Application-facing repository and unit-of-work protocols."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from .entities import (
    CatPost,
    CatThread,
    CatVideoSubmission,
    MessagePurpose,
    SourceIdentity,
    TelegramMessageRef,
    TelegramProjection,
)


class SubmissionRepository(Protocol):
    async def create(
        self,
        *,
        source_provider: str,
        source_media_id: str,
        source_channel_id: str | None = None,
        status: str = "pending",
    ) -> CatVideoSubmission: ...

    async def get_by_source_media(
        self, source_provider: str, source_media_id: str
    ) -> CatVideoSubmission | None: ...


class ThreadRepository(Protocol):
    async def get_or_create(self, source: SourceIdentity) -> CatThread: ...

    async def get(self, thread_id: str) -> CatThread | None: ...

    async def contains_post(self, thread_id: str, post_id: str) -> bool: ...

    async def add_post(
        self,
        *,
        thread_id: str,
        submission_id: str,
        parent_post_id: str | None = None,
    ) -> CatPost: ...

    async def initialize_root(
        self, *, thread_id: str, post_id: str, expected_version: int
    ) -> CatThread: ...

    async def advance_tail(
        self,
        *,
        thread_id: str,
        post_id: str,
        expected_tail_id: str,
        expected_version: int,
    ) -> CatThread: ...


class ProjectionRepository(Protocol):
    async def add_for_post(
        self, *, post_id: str, purpose: MessagePurpose, reference: TelegramMessageRef
    ) -> TelegramProjection: ...

    async def add_for_submission(
        self,
        *,
        submission_id: str,
        purpose: MessagePurpose,
        reference: TelegramMessageRef,
    ) -> TelegramProjection: ...

    async def get_by_reference(
        self, reference: TelegramMessageRef
    ) -> TelegramProjection | None: ...


class PersistenceUnitOfWork(Protocol):
    @property
    def submissions(self) -> SubmissionRepository: ...

    @property
    def threads(self) -> ThreadRepository: ...

    @property
    def projections(self) -> ProjectionRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
