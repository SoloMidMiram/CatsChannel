"""Source-aware submission decisions with short, explicit transactions."""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..persistence.contracts import PersistenceUnitOfWork
from ..persistence.entities import CatThread, HandoffRequest
from ..persistence.errors import (
    DuplicateHandoffTokenError,
    DuplicateSourceMediaError,
    DuplicateTelegramMessageError,
    PersistenceError,
    ThreadNotFoundError,
)
from .entities import (
    HandoffBinding,
    HandoffClaim,
    IssuedHandoff,
    ResolvedSourceIdentity,
    SubmissionMedia,
    SubmissionRequest,
    SubmissionResult,
    ValidatedTelegramMedia,
)
from .errors import SubmissionError
from .resolvers import SourceIdentityResolver

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _token_digest(token: str) -> str:
    if not _TOKEN_PATTERN.fullmatch(token):
        raise SubmissionError("handoff_invalid")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class SubmissionService:
    """Validate source assignment and atomically persist one submission."""

    def __init__(
        self,
        unit_of_work: Callable[[], PersistenceUnitOfWork],
        source_resolver: SourceIdentityResolver,
        *,
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._source_resolver = source_resolver
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("SubmissionService clock must be timezone-aware")
        return value.astimezone(UTC)

    async def issue_handoff(
        self, binding: HandoffBinding, *, ttl_seconds: int = 300
    ) -> IssuedHandoff:
        if not 30 <= ttl_seconds <= 900:
            raise ValueError("ttl_seconds must be between 30 and 900")
        token = self._token_factory()
        digest = _token_digest(token)
        expires_at = self._now() + timedelta(seconds=ttl_seconds)
        try:
            async with self._unit_of_work() as uow:
                await uow.handoffs.create(
                    token_digest=digest,
                    actor_id=binding.actor_id,
                    conversation_chat_id=binding.conversation_chat_id,
                    operation=binding.operation,
                    expires_at=expires_at,
                )
        except asyncio.CancelledError:
            raise
        except DuplicateHandoffTokenError as error:
            raise SubmissionError("submission_persistence") from error
        except Exception as error:
            raise SubmissionError("submission_persistence") from error
        return IssuedHandoff(token=token, expires_at=expires_at)

    async def submit(self, request: SubmissionRequest) -> SubmissionResult:
        if (
            isinstance(request.media, ValidatedTelegramMedia)
            and request.handoff is not None
            and request.media.reference.chat_id != request.handoff.binding.conversation_chat_id
        ):
            raise SubmissionError("handoff_invalid")
        try:
            resolution = await self._source_resolver.resolve(request.media)
        except asyncio.CancelledError:
            raise
        except SubmissionError:
            raise
        except Exception as error:
            raise SubmissionError("source_identity_unresolved") from error
        self._validate_resolution(request.media, resolution)
        try:
            async with self._unit_of_work() as uow:
                await self._require_pending_handoff(uow, request.handoff)
                thread, identity_status = await self._resolve_thread(uow, request, resolution)
                provenance = {
                    "media": dict(request.media.provenance),
                    "source_resolution": {
                        "status": resolution.status,
                        "method": resolution.method,
                        "evidence": dict(resolution.evidence),
                    },
                }
                if isinstance(request.media, ValidatedTelegramMedia):
                    provenance["telegram"] = {
                        "file_id": request.media.file_id,
                        "file_unique_id": request.media.file_unique_id,
                    }
                submission = await uow.submissions.create(
                    source_provider=request.media.source_provider,
                    source_media_id=request.media.source_media_id,
                    source_channel_id=thread.source.channel_id,
                    source_channel_name=thread.source.channel_name,
                    source_channel_username=thread.source.channel_username,
                    source_identity_status=identity_status,
                    thread_id=thread.id,
                    status="validated",
                    media_origin=request.media.origin,
                    media_metadata=request.media.metadata.to_record(),
                    validation_evidence=request.media.validation.to_record(),
                    provenance=provenance,
                )
                if isinstance(request.media, ValidatedTelegramMedia):
                    await uow.projections.add_for_submission(
                        submission_id=submission.id,
                        purpose="private",
                        reference=request.media.reference,
                    )
                if request.handoff is not None:
                    await self._consume_handoff(uow, request.handoff, submission.id)
                result = SubmissionResult(
                    disposition="created",
                    submission_id=submission.id,
                    thread_id=thread.id,
                    lifecycle="validated",
                    source_identity_status=identity_status,
                )
            return result
        except asyncio.CancelledError:
            raise
        except SubmissionError:
            raise
        except DuplicateSourceMediaError as error:
            raise SubmissionError("duplicate_media") from error
        except DuplicateTelegramMessageError as error:
            raise SubmissionError("handoff_invalid") from error
        except ThreadNotFoundError as error:
            raise SubmissionError("source_selection_invalid") from error
        except PersistenceError as error:
            raise SubmissionError("submission_persistence") from error
        except Exception as error:
            raise SubmissionError("submission_persistence") from error

    async def reconcile_handoff(self, claim: HandoffClaim) -> SubmissionResult | None:
        """Resolve an ambiguous commit before an operator-authorized retry."""
        try:
            async with self._unit_of_work() as uow:
                handoff = await self._bound_handoff(uow, claim)
                if not handoff.consumed:
                    if handoff.expires_at <= self._now():
                        raise SubmissionError("handoff_invalid")
                    return None
                submission = await uow.submissions.get(str(handoff.submission_id))
                if (
                    submission is None
                    or submission.thread_id is None
                    or submission.source_identity_status not in {"verified", "user_selected"}
                ):
                    raise SubmissionError("submission_persistence")
                return SubmissionResult(
                    disposition="existing",
                    submission_id=submission.id,
                    thread_id=submission.thread_id,
                    lifecycle="validated",
                    source_identity_status=submission.source_identity_status,
                )
        except asyncio.CancelledError:
            raise
        except SubmissionError:
            raise
        except Exception as error:
            raise SubmissionError("submission_persistence") from error

    @staticmethod
    def _validate_resolution(media: SubmissionMedia, resolution: ResolvedSourceIdentity) -> None:
        if (
            resolution.status == "verified"
            and resolution.identity is not None
            and resolution.identity.provider != media.source_provider
        ):
            raise SubmissionError("source_identity_conflict")

    async def _resolve_thread(
        self,
        uow: PersistenceUnitOfWork,
        request: SubmissionRequest,
        resolution: ResolvedSourceIdentity,
    ) -> tuple[CatThread, str]:
        if resolution.status == "verified" and resolution.identity is not None:
            thread = await uow.threads.get_or_create(resolution.identity)
            if request.selected_thread_id is not None and request.selected_thread_id != thread.id:
                raise SubmissionError("source_identity_conflict")
            return thread, "verified"
        if request.selected_thread_id is None:
            raise SubmissionError("source_identity_unresolved")
        thread = await uow.threads.get(request.selected_thread_id)
        if thread is None or thread.source.provider != request.media.source_provider:
            raise SubmissionError("source_selection_invalid")
        return thread, "user_selected"

    async def _bound_handoff(
        self, uow: PersistenceUnitOfWork, claim: HandoffClaim
    ) -> HandoffRequest:
        handoff = await uow.handoffs.get_bound(
            token_digest=_token_digest(claim.token),
            actor_id=claim.binding.actor_id,
            conversation_chat_id=claim.binding.conversation_chat_id,
            operation=claim.binding.operation,
        )
        if handoff is None:
            raise SubmissionError("handoff_invalid")
        return handoff

    async def _require_pending_handoff(
        self, uow: PersistenceUnitOfWork, claim: HandoffClaim | None
    ) -> None:
        if claim is None:
            return
        handoff = await self._bound_handoff(uow, claim)
        if handoff.consumed:
            raise SubmissionError("handoff_invalid")
        if handoff.expires_at <= self._now():
            raise SubmissionError("handoff_invalid")

    async def _consume_handoff(
        self,
        uow: PersistenceUnitOfWork,
        claim: HandoffClaim,
        submission_id: str,
    ) -> None:
        handoff = await self._bound_handoff(uow, claim)
        if handoff.consumed:
            raise SubmissionError("handoff_invalid")
        if not await uow.handoffs.consume(
            handoff_id=handoff.id,
            submission_id=submission_id,
            consumed_at=self._now(),
        ):
            raise SubmissionError("handoff_invalid")
