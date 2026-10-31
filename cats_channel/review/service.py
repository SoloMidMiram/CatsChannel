"""One review copy, one authenticated decision, existing publication ownership."""

import asyncio
import logging
from datetime import UTC, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..async_cleanup import complete_cleanup
from ..diagnostics import log_failure
from ..errors import MediaError
from ..publication.errors import DeliveryRejected
from ..reply_tokens import internal_id
from .entities import ReviewError


class ReviewService:
    def __init__(
        self,
        unit_of_work,
        *,
        transport,
        publication_service,
        review_chat_id,
        destination_chat_id,
        admin_user_id,
        logger=None,
    ):
        self.unit_of_work = unit_of_work
        self.transport = transport
        self.publisher = publication_service
        self.review_chat = review_chat_id
        self.destination = destination_chat_id
        self.admin = admin_user_id
        self.logger = logger or logging.getLogger("cats_channel")

    async def get(self, item_id):
        async with self.unit_of_work() as uow:
            return await uow.reviews.get(item_id)

    async def recover_abandoned(self, **kwargs):
        async with self.unit_of_work() as uow:
            await uow.reviews.recover_abandoned()

    def failure(self, event, phase, code):
        log_failure(
            self.logger,
            event,
            MediaError(code=code, log_analysis={"phase": phase, "raw_log_included": False}),
            operation="review",
        )

    async def enqueue(self, submission_id):
        internal_id(submission_id)
        async with self.unit_of_work() as uow:
            submission = await uow.submissions.get(submission_id)
            intent = await uow.intents.get_for_submission(submission_id)
            if not submission or submission.status != "validated" or not intent:
                raise ReviewError("review_not_eligible")
            item = await uow.reviews.create(submission_id, self.review_chat, self.destination)
            if not await uow.reviews.claim_delivery(item):
                return await uow.reviews.get(item.id)
        # Ownership is committed before the single external media send.
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Approve", callback_data=f"reviewapprove:{item.id}:{item.version}"
                    )
                ]
            ]
        )
        caption = "Pending review\nApprove to publish this video"
        caption += (
            " as a reply to the selected post."
            if intent.mode == "interactive_reply"
            else " to the channel."
        )
        caption += "\nSource identity: " + (
            "verified" if submission.source_identity_status == "verified" else "unverified"
        )
        try:
            reference = await self.transport.send_review(
                submission, caption=caption, reply_markup=markup
            )
            if reference.chat_id != self.review_chat or reference.message_id <= 0:
                raise ReviewError("review_delivery_unknown")
        except asyncio.CancelledError:
            await complete_cleanup(
                self._finish_delivery(item, "unknown", error="review_delivery_unknown")
            )
            raise
        except DeliveryRejected:
            return await self._finish_delivery(item, "failed", error="review_delivery_rejected")
        except Exception:  # noqa: BLE001 - ambiguous external send must not be retried
            return await self._finish_delivery(item, "unknown", error="review_delivery_unknown")
        return await self._finish_delivery(item, "confirmed", message_id=reference.message_id)

    async def _finish_delivery(self, item, state, **fields):
        async with self.unit_of_work() as uow:
            result = await uow.reviews.finish_delivery(item, state, **fields)
        if state != "confirmed":
            self.failure(
                "review_delivery_failure", "review_send", fields.get("error", "review_unavailable")
            )
        return result

    async def approve(self, item_id, version, *, actor_id, chat_id, message_id):
        if actor_id != self.admin:
            raise ReviewError("review_forbidden")
        internal_id(item_id)
        async with self.unit_of_work() as uow:
            item = await uow.reviews.get(item_id)
            if (
                not item
                or item.review_chat_id != self.review_chat
                or item.review_chat_id != chat_id
                or item.message_id != message_id
                or item.destination_chat_id != self.destination
                or item.delivery_state != "confirmed"
            ):
                raise ReviewError("review_message_mismatch")
            if item.decision_state != "pending":
                return item
            if item.version != version:
                raise ReviewError("review_stale")
            if not await uow.reviews.claim_approval(item, actor_id, datetime.now(UTC)):
                return await uow.reviews.get(item_id)
        # A committed audit decision owns this invocation; concurrent clicks cannot send.
        try:
            publication = await self.publisher.approve_pilot(item.submission_id)
        except asyncio.CancelledError:
            await complete_cleanup(
                self._finish_approval(
                    item, "needs_reconciliation", error="review_approval_interrupted"
                )
            )
            raise
        except Exception:  # noqa: BLE001 - preserve durable approval ownership on failure
            return await self._finish_approval(
                item, "needs_reconciliation", error="review_publication_unavailable"
            )
        decision = "approved" if publication.state == "confirmed" else "needs_reconciliation"
        if publication.state == "blocked":
            decision = "blocked"
        return await self._finish_approval(
            item, decision, publication_id=publication.id, error=publication.error_category
        )

    async def _finish_approval(self, item, state, **fields):
        async with self.unit_of_work() as uow:
            return await uow.reviews.finish_approval(item, state, **fields)
