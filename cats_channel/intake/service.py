"""Authenticated intake orchestration without publication or moderation effects."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from ..persistence.contracts import PersistenceUnitOfWork
from ..persistence.entities import CatVideoSubmission, TelegramMessageRef
from ..reply_chains.coordinator import ThreadCoordinator
from ..reply_chains.entities import PlacementMode, PostIntent
from ..reply_chains.errors import ReplyChainError
from ..reply_chains.service import ReplyChainService
from ..reply_tokens import ReplyTarget
from ..submissions import (
    HandoffBinding,
    HandoffClaim,
    SourceIdentityResolver,
    SubmissionError,
    SubmissionRequest,
    SubmissionService,
)
from ..submissions.entities import SubmissionMedia
from .entities import IntakePlacement, IntakeResult, SourceOption
from .errors import IntakeError

_OPERATION = "bot_post_intake"


class SubmissionIntakeService:
    """Reconcile first, acquire once, then persist a submission and pending intent."""

    def __init__(
        self,
        unit_of_work: Callable[[], PersistenceUnitOfWork],
        source_resolver: SourceIdentityResolver,
        *,
        submissions: SubmissionService | None = None,
        reply_chains: ReplyChainService | None = None,
        coordinator: ThreadCoordinator | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        submission_kwargs = {} if clock is None else {"clock": clock}
        self._submissions = submissions or SubmissionService(
            unit_of_work, source_resolver, **submission_kwargs
        )
        self._reply_chains = reply_chains or ReplyChainService(unit_of_work)
        self._coordinator = coordinator or ThreadCoordinator()

    @property
    def pending_count(self) -> int:
        return self._coordinator.pending_count

    async def list_source_options(self, *, limit: int = 20) -> tuple[SourceOption, ...]:
        try:
            async with self._unit_of_work() as uow:
                threads = await uow.threads.list_sources(limit=limit)
            return tuple(
                SourceOption(
                    thread.id,
                    thread.source.provider,
                    thread.source.channel_name
                    or thread.source.channel_username
                    or f"{thread.source.provider} source",
                )
                for thread in threads
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise IntakeError("intake_persistence") from error

    async def require_compatible_provider(
        self, placement: IntakePlacement, source_provider: str
    ) -> None:
        if placement.mode == "interactive_reply":
            return
        if placement.thread_id is None:
            if source_provider != "youtube":
                raise SubmissionError("source_identity_unresolved")
            return
        try:
            async with self._unit_of_work() as uow:
                thread = await uow.threads.get(placement.thread_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise IntakeError("intake_persistence") from error
        if thread is None or thread.source.provider != source_provider:
            raise SubmissionError("source_selection_invalid")

    async def process(
        self,
        *,
        actor_id: int,
        inbound_reference: TelegramMessageRef,
        placement: IntakePlacement,
        acquire: Callable[[], Awaitable[SubmissionMedia]],
        continue_if: Callable[[], Awaitable[bool]] | None = None,
    ) -> IntakeResult:
        if type(actor_id) is not int or actor_id <= 0:
            raise IntakeError("intake_conflict")
        if not isinstance(inbound_reference, TelegramMessageRef) or not isinstance(
            placement, IntakePlacement
        ):
            raise IntakeError("intake_conflict")
        key = f"{inbound_reference.chat_id}:{inbound_reference.message_id}"
        async with self._coordinator.hold(key):
            existing = await self._reconcile(actor_id, inbound_reference, placement)
            if existing is not None:
                return existing
            media = await acquire()
            if continue_if is not None and not await continue_if():
                raise IntakeError("intake_superseded")
            binding = HandoffBinding(
                actor_id=actor_id,
                conversation_chat_id=inbound_reference.chat_id,
                operation=_OPERATION,
            )
            issued = await self._submissions.issue_handoff(binding)
            request = SubmissionRequest(
                media=media,
                selected_thread_id=(
                    placement.thread_id if placement.mode == "normal_append" else None
                ),
                handoff=HandoffClaim(issued.token, binding),
                authorized_reply_target=(
                    ReplyTarget(placement.selected_parent_post_id, placement.thread_id)
                    if placement.mode == "interactive_reply"
                    else None
                ),
                inbound_reference=inbound_reference,
            )
            try:
                submitted = await self._submissions.submit(request)
            except asyncio.CancelledError:
                raise
            except SubmissionError as error:
                if error.code in {"handoff_invalid", "submission_persistence"}:
                    reconciled = await self._reconcile(actor_id, inbound_reference, placement)
                    if reconciled is not None:
                        return reconciled
                raise
            intent = await self._create_intent(
                submitted.submission_id,
                submitted.thread_id,
                placement.mode,
                placement.selected_parent_post_id,
            )
            return IntakeResult(
                "created",
                submitted.submission_id,
                intent.id,
                submitted.thread_id,
                placement.mode,
            )

    async def _reconcile(
        self,
        actor_id: int,
        reference: TelegramMessageRef,
        placement: IntakePlacement,
    ) -> IntakeResult | None:
        try:
            async with self._unit_of_work() as uow:
                projection = await uow.projections.get_by_reference(reference)
                if projection is None:
                    return None
                if projection.purpose != "private" or projection.submission_id is None:
                    raise IntakeError("intake_conflict")
                submission = await uow.submissions.get(projection.submission_id)
                handoff = await uow.handoffs.get_for_submission(projection.submission_id)
                intent = await uow.intents.get_for_submission(projection.submission_id)
            if submission is None or handoff is None:
                raise IntakeError("intake_conflict")
            if (
                handoff.actor_id != actor_id
                or handoff.conversation_chat_id != reference.chat_id
                or handoff.operation != _OPERATION
                or not handoff.consumed
                or handoff.submission_id != submission.id
                or not self._placement_matches(submission, placement)
            ):
                raise IntakeError("intake_conflict")
            if intent is not None:
                self._require_intent_matches(submission, intent)
                return IntakeResult(
                    "existing",
                    submission.id,
                    intent.id,
                    str(submission.thread_id),
                    intent.mode,
                )
            if submission.thread_id is None or submission.placement_mode not in {
                "normal_append",
                "interactive_reply",
            }:
                raise IntakeError("intake_conflict")
            created = await self._create_intent(
                submission.id,
                submission.thread_id,
                submission.placement_mode,
                submission.selected_parent_post_id,
            )
            return IntakeResult(
                "recovered",
                submission.id,
                created.id,
                str(submission.thread_id),
                created.mode,
            )
        except asyncio.CancelledError:
            raise
        except (IntakeError, ReplyChainError):
            raise
        except Exception as error:
            raise IntakeError("intake_persistence") from error

    @staticmethod
    def _placement_matches(submission: CatVideoSubmission, placement: IntakePlacement) -> bool:
        return (
            submission.thread_id is not None
            and submission.placement_mode == placement.mode
            and submission.selected_parent_post_id == placement.selected_parent_post_id
            and (placement.thread_id is None or submission.thread_id == placement.thread_id)
        )

    @staticmethod
    def _require_intent_matches(submission: CatVideoSubmission, intent: PostIntent) -> None:
        if (
            submission.thread_id is None
            or submission.placement_mode != intent.mode
            or submission.thread_id != intent.thread_id
            or submission.selected_parent_post_id != intent.selected_parent_post_id
        ):
            raise IntakeError("intake_conflict")

    async def _create_intent(
        self,
        submission_id: str,
        thread_id: str,
        mode: PlacementMode,
        parent_post_id: str | None,
    ) -> PostIntent:
        if mode == "normal_append" and parent_post_id is None:
            create = self._reply_chains.create_normal_intent(submission_id, thread_id)
        elif mode == "interactive_reply" and parent_post_id is not None:
            create = self._reply_chains.create_interactive_intent(
                submission_id, thread_id, parent_post_id
            )
        else:
            raise IntakeError("intake_conflict")
        try:
            return await create
        except asyncio.CancelledError:
            raise
        except ReplyChainError as error:
            if error.code != "reply_intent_conflict":
                raise
            async with self._unit_of_work() as uow:
                submission = await uow.submissions.get(submission_id)
                intent = await uow.intents.get_for_submission(submission_id)
            if submission is None or intent is None:
                raise
            self._require_intent_matches(submission, intent)
            return intent
