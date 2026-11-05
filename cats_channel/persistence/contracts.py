"""Application-facing repository and unit-of-work protocols."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from ..discovery.contracts import WatchlistRepository
from ..publication.contracts import PublicationRepository
from ..reply_chains.contracts import IntentRepository, ReplyTokenRepository
from .entities import (
    CatPost,
    CatThread,
    CatVideoSubmission,
    HandoffRequest,
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
        source_channel_name: str | None = None,
        source_channel_username: str | None = None,
        source_identity_status: str = "unresolved",
        thread_id: str | None = None,
        status: str = "pending",
        media_origin: str = "legacy",
        media_metadata: dict[str, object] | None = None,
        validation_evidence: dict[str, object] | None = None,
        provenance: dict[str, object] | None = None,
        placement_mode: str | None = None,
        selected_parent_post_id: str | None = None,
    ) -> CatVideoSubmission: ...

    async def get(self, submission_id: str) -> CatVideoSubmission | None: ...

    async def lock(self, submission_id: str) -> None:
        """Serialize rejection and placement until this unit of work ends."""
        ...

    async def get_by_source_media(
        self, source_provider: str, source_media_id: str
    ) -> CatVideoSubmission | None: ...


class ThreadRepository(Protocol):
    async def get_post(self, post_id: str) -> CatPost | None: ...

    async def get_post_for_submission(self, submission_id: str) -> CatPost | None: ...

    async def get_or_create(self, source: SourceIdentity) -> CatThread: ...

    async def get(self, thread_id: str) -> CatThread | None: ...

    async def list_sources(self, *, limit: int = 20) -> tuple[CatThread, ...]: ...

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
    async def get_destination(self, *, post_id: str, chat_id: int) -> TelegramProjection | None: ...

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


class HandoffRepository(Protocol):
    async def create(
        self,
        *,
        token_digest: str,
        actor_id: int,
        conversation_chat_id: int,
        operation: str,
        expires_at: datetime,
    ) -> HandoffRequest: ...

    async def get_bound(
        self,
        *,
        token_digest: str,
        actor_id: int,
        conversation_chat_id: int,
        operation: str,
    ) -> HandoffRequest | None: ...

    async def get_for_submission(self, submission_id: str) -> HandoffRequest | None: ...

    async def consume(
        self,
        *,
        handoff_id: str,
        submission_id: str,
        consumed_at: datetime,
    ) -> bool: ...


class PersistenceUnitOfWork(Protocol):
    @property
    def watchlist(self) -> WatchlistRepository: ...

    @property
    def reviews(self): ...

    @property
    def publications(self) -> PublicationRepository: ...

    @property
    def intents(self) -> IntentRepository: ...

    @property
    def reply_tokens(self) -> ReplyTokenRepository: ...

    @property
    def submissions(self) -> SubmissionRepository: ...

    @property
    def threads(self) -> ThreadRepository: ...

    @property
    def projections(self) -> ProjectionRepository: ...

    @property
    def handoffs(self) -> HandoffRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
