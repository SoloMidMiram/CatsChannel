"""Explicit pilot approval, durable attempt ownership, and conservative recovery."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from ..async_cleanup import complete_cleanup
from ..diagnostics import log_operation, log_publication
from ..persistence.contracts import PersistenceUnitOfWork
from ..persistence.entities import CatPost, CatVideoSubmission, TelegramMessageRef
from ..reply_chains.service import ReplyChainService
from ..reply_tokens import EntryContractError, internal_id
from .contracts import PublicationTransport
from .coordinator import PublicationCoordinator
from .entities import Attempt, Publication
from .errors import DeliveryRejected, PublicationError


class PublicationService:
    def __init__(
        self,
        unit_of_work: Callable[[], PersistenceUnitOfWork],
        *,
        reply_chains: ReplyChainService,
        transport: PublicationTransport,
        destination_chat_id: int,
        coordinator: PublicationCoordinator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        logger: logging.Logger | None = None,
    ):
        if type(destination_chat_id) is not int or destination_chat_id == 0:
            raise ValueError("Expected numeric destination")
        if reply_chains.destination_chat_id != destination_chat_id:
            raise ValueError("Reply chain destination mismatch")
        self.unit_of_work = unit_of_work
        self.chains = reply_chains
        self.transport = transport
        self.destination = destination_chat_id
        self.coordinator = coordinator or PublicationCoordinator()
        self.clock = clock
        self.logger = logger or logging.getLogger(__name__)

    async def approve_pilot(self, submission_id: str) -> Publication:
        """Trusted admin command boundary: invocation explicitly approves this intent only."""
        started = time.monotonic()
        try:
            internal_id(submission_id)
            async with self.unit_of_work() as uow:
                submission = await uow.submissions.get(submission_id)
                intent = await uow.intents.get_for_submission(submission_id)
                if submission is None or submission.status != "validated" or intent is None:
                    raise PublicationError("publication_not_eligible")
            async with self.coordinator.hold(intent.thread_id):
                # Placement may already have committed in an earlier interrupted request.
                async with self.unit_of_work() as uow:
                    post = await uow.threads.get_post_for_submission(submission_id)
                if post is None:
                    await self.chains.finalize_intent(intent.id)
                async with self.unit_of_work() as uow:
                    post = await uow.threads.get_post_for_submission(submission_id)
                    publication = await uow.publications.get_for_post(post.id, self.destination)
                    if publication is None:
                        publication = await uow.publications.create(post.id, self.destination)
                result = await self._publish(post, publication, submission)
            log_operation(
                self.logger,
                correlation_id=result.id,
                operation="pilot_publish",
                outcome=result.state,
                duration_ms=(time.monotonic() - started) * 1000,
            )
            return result
        except EntryContractError:
            raise PublicationError("publication_not_eligible") from None
        except PublicationError:
            raise
        except Exception:  # noqa: BLE001 - safe application/transport boundary
            raise PublicationError() from None

    async def _publish(
        self, post: CatPost, publication: Publication, submission: CatVideoSubmission
    ) -> Publication:
        if publication.state == "confirmed":
            await self._repair_related(post)
            return await self._get(publication.id)
        # A repeated request cannot take ownership of sending, unknown or failed.
        if publication.state in {"sending", "unknown", "failed"}:
            return publication
        parent = None
        async with self.unit_of_work() as uow:
            existing_projection = await uow.projections.get_destination(
                post_id=post.id, chat_id=self.destination
            )
            if post.parent_post_id:
                parent_post = await uow.threads.get_post(post.parent_post_id)
                parent_pub = await uow.publications.get_for_post(
                    post.parent_post_id, self.destination
                )
                projection = await uow.projections.get_destination(
                    post_id=post.parent_post_id, chat_id=self.destination
                )
                if (
                    parent_post is None
                    or parent_post.thread_id != post.thread_id
                    or parent_pub is None
                    or parent_pub.state != "confirmed"
                    or projection is None
                ):
                    if publication.state == "pending":
                        publication = await uow.publications.transition(
                            publication, "blocked", category="parent_unconfirmed"
                        )
                    return publication
                parent = projection.reference
            if publication.state == "blocked":
                publication = await uow.publications.transition(publication, "pending")
            attempt = await uow.publications.claim(publication, self.clock())
        # Claim transaction is closed before any media access or network operation.
        log_publication(
            self.logger,
            publication_id=publication.id,
            phase="dispatch",
            state="sending",
            attempt_number=attempt.number,
        )
        if existing_projection is not None:
            # Legacy/manual delivery evidence must never cause a duplicate send.
            await self._outcome(publication.id, attempt, "unknown", "existing_projection_review")
            return await self._get(publication.id)
        try:
            reference = await self.transport.send(submission, parent=parent)
            await self._confirm(publication.id, attempt, reference)
        except asyncio.CancelledError:
            await self._safe_uncertainty(publication.id, attempt, "dispatch_cancelled")
            raise
        except DeliveryRejected:
            await self._outcome(publication.id, attempt, "failed", "delivery_rejected")
        except Exception:  # noqa: BLE001 - possibly dispatched, never blindly retry
            await self._safe_uncertainty(publication.id, attempt, "delivery_uncertain")
        result = await self._get(publication.id)
        if result.state == "confirmed":
            await self._repair_related(post)
            result = await self._get(publication.id)
        return result

    async def _get(self, publication_id: str) -> Publication:
        async with self.unit_of_work() as uow:
            result = await uow.publications.get(publication_id)
            if result is None:
                raise PublicationError("publication_not_found")
            return result

    async def _confirm(
        self, publication_id: str, attempt: Attempt, reference: TelegramMessageRef
    ) -> None:
        if (
            not isinstance(reference, TelegramMessageRef)
            or type(reference.chat_id) is not int
            or reference.chat_id != self.destination
            or type(reference.message_id) is not int
            or reference.message_id <= 0
        ):
            raise PublicationError("delivery_coordinates_invalid")
        async with self.unit_of_work() as uow:
            publication = await uow.publications.get(publication_id)
            existing = await uow.projections.get_destination(
                post_id=publication.post_id, chat_id=self.destination
            )
            if existing is None:
                await uow.projections.add_for_post(
                    post_id=publication.post_id, purpose="destination", reference=reference
                )
            elif existing.reference != reference:
                raise PublicationError("delivery_coordinates_conflict")
            await uow.publications.finish(
                publication, attempt, "confirmed", self.clock(), recovery="confirmed_reference"
            )
            post = await uow.threads.get_post(publication.post_id)
            if post.parent_post_id:
                parent = await uow.publications.get_for_post(post.parent_post_id, self.destination)
                if parent and parent.state == "confirmed":
                    await uow.publications.set_navigation(parent.id, post.id)
        log_publication(
            self.logger,
            publication_id=publication_id,
            phase="confirmation",
            state="confirmed",
            attempt_number=attempt.number,
        )

    async def _outcome(self, publication_id, attempt, state, category):
        async with self.unit_of_work() as uow:
            publication = await uow.publications.get(publication_id)
            # Commit acknowledgement may have been lost after a successful commit.
            if publication.state == "confirmed":
                return
            await uow.publications.finish(
                publication,
                attempt,
                state,
                self.clock(),
                category=category,
                recovery="operator_required" if state == "unknown" else "known_rejection",
            )
        log_publication(
            self.logger,
            publication_id=publication_id,
            phase="outcome",
            state=state,
            attempt_number=attempt.number,
            error_category=category,
            recovery_action="operator_required" if state == "unknown" else "explicit_retry",
        )

    async def _safe_uncertainty(self, publication_id, attempt, category):
        async def record():
            async with asyncio.timeout(10):
                await self._outcome(publication_id, attempt, "unknown", category)

        try:
            await complete_cleanup(record())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - durable sending remains non-retryable
            log_operation(
                self.logger,
                correlation_id=publication_id,
                duration_ms=0,
                operation="publication",
                outcome="sending",
                error_category="uncertainty_persistence_failed",
            )

    async def recover_abandoned(self) -> None:
        """Startup only, before accepting updates. No lease expiry ever permits resend."""
        async with self.unit_of_work() as uow:
            for publication in await uow.publications.list_sending():
                attempt = await uow.publications.current_attempt(publication)
                await uow.publications.finish(
                    publication,
                    attempt,
                    "unknown",
                    self.clock(),
                    category="process_interrupted",
                    recovery="operator_required",
                )

    async def reconcile(
        self,
        publication_id: str,
        *,
        reference: TelegramMessageRef | None = None,
        non_delivery_proven: bool = False,
    ) -> Publication:
        """Trusted operator API: evidence must be independently inspected, never inferred."""
        internal_id(publication_id)
        if (reference is None) == (not non_delivery_proven):
            raise PublicationError("reconciliation_evidence_required")
        publication = await self._get(publication_id)
        async with self.unit_of_work() as uow:
            post = await uow.threads.get_post(publication.post_id)
        async with self.coordinator.hold(post.thread_id):
            publication = await self._get(publication_id)
            if publication.state != "unknown":
                raise PublicationError("publication_transition_invalid")
            async with self.unit_of_work() as uow:
                attempt = await uow.publications.current_attempt(publication)
            if reference is not None:
                await self._confirm(publication_id, attempt, reference)
                await self._repair_related(post)
            else:
                await self._outcome(publication_id, attempt, "failed", "operator_non_delivery")
            return await self._get(publication_id)

    async def requeue_failed(self, publication_id: str) -> Publication:
        """Explicit controlled retry, only after known non-delivery; does not send."""
        publication = await self._get(internal_id(publication_id))
        if publication.state != "failed":
            raise PublicationError("publication_transition_invalid")
        async with self.unit_of_work() as uow:
            return await uow.publications.transition(publication, "pending")

    async def _repair_related(self, post):
        for post_id in (post.id, post.parent_post_id):
            if post_id is None:
                continue
            async with self.unit_of_work() as uow:
                publication = await uow.publications.get_for_post(post_id, self.destination)
            if (
                publication
                and publication.state == "confirmed"
                and publication.markup_status != "installed"
            ):
                await self._repair_markup(publication)

    async def repair_markup(self, publication_id: str) -> Publication:
        publication = await self._get(internal_id(publication_id))
        async with self.unit_of_work() as uow:
            post = await uow.threads.get_post(publication.post_id)
        async with self.coordinator.hold(post.thread_id):
            publication = await self._get(publication_id)
            if publication.state != "confirmed":
                raise PublicationError("publication_transition_invalid")
            await self._repair_markup(publication)
            return await self._get(publication_id)

    async def _repair_markup(self, publication):
        try:
            async with self.unit_of_work() as uow:
                projection = await uow.projections.get_destination(
                    post_id=publication.post_id, chat_id=self.destination
                )
                child = None
                if publication.navigation_post_id:
                    child_pub = await uow.publications.get_for_post(
                        publication.navigation_post_id, self.destination
                    )
                    child_post = await uow.threads.get_post(publication.navigation_post_id)
                    if (
                        child_pub
                        and child_pub.state == "confirmed"
                        and child_post.parent_post_id == publication.post_id
                    ):
                        child = await uow.projections.get_destination(
                            post_id=child_pub.post_id, chat_id=self.destination
                        )
                if projection is None:
                    raise PublicationError("projection_unavailable")
            issued = await self.chains.issue_reply_token(
                publication.post_id, publication_id=publication.id
            )
            await self.transport.install_markup(
                projection.reference, token=issued.token, child=child.reference if child else None
            )
        except asyncio.CancelledError:
            # pending token/markup is restart-repairable; media stays confirmed.
            raise
        except Exception:  # noqa: BLE001 - markup cannot change media delivery state
            async with self.unit_of_work() as uow:
                await uow.publications.set_markup(publication.id, "failed")
        else:
            async with self.unit_of_work() as uow:
                await uow.publications.set_markup(publication.id, "installed")
