"""Atomic review delivery and approval ownership within the existing unit of work."""

from dataclasses import fields
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..review.entities import ReviewItem
from .models import CatVideoSubmissionModel, ReviewItemModel


def snapshot(model):
    return ReviewItem(**{field.name: getattr(model, field.name) for field in fields(ReviewItem)})


class SqlAlchemyReviewRepository:
    def __init__(self, session):
        self.session = session

    async def get(self, item_id):
        model = await self.session.scalar(
            select(ReviewItemModel)
            .where(ReviewItemModel.id == item_id)
            .execution_options(populate_existing=True)
        )
        return snapshot(model) if model else None

    async def for_submission(self, submission_id, chat_id):
        model = await self.session.scalar(
            select(ReviewItemModel)
            .where(
                ReviewItemModel.submission_id == submission_id,
                ReviewItemModel.review_chat_id == chat_id,
            )
            .execution_options(populate_existing=True)
        )
        return snapshot(model) if model else None

    async def create(self, submission_id, chat_id, destination):
        existing = await self.for_submission(submission_id, chat_id)
        if existing:
            return existing
        model = ReviewItemModel(
            id=str(uuid4()),
            submission_id=submission_id,
            review_chat_id=chat_id,
            destination_chat_id=destination,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError:
            existing = await self.for_submission(submission_id, chat_id)
            if existing:
                return existing
            raise
        await self.session.refresh(model)
        return snapshot(model)

    async def claim_delivery(self, item):
        result = await self.session.execute(
            update(ReviewItemModel)
            .where(
                ReviewItemModel.id == item.id,
                ReviewItemModel.delivery_state == "pending",
                ReviewItemModel.version == item.version,
            )
            .values(delivery_state="sending")
        )
        return result.rowcount == 1

    async def finish_delivery(self, item, state, *, message_id=None, error=None):
        await self.session.execute(
            update(ReviewItemModel)
            .where(
                ReviewItemModel.id == item.id,
                ReviewItemModel.delivery_state == "sending",
                ReviewItemModel.version == item.version,
            )
            .values(delivery_state=state, message_id=message_id, error_category=error)
        )
        return await self.get(item.id)

    async def claim_approval(self, item, actor_id, now):
        result = await self.session.execute(
            update(ReviewItemModel)
            .where(
                ReviewItemModel.id == item.id,
                ReviewItemModel.delivery_state == "confirmed",
                ReviewItemModel.decision_state == "pending",
                ReviewItemModel.version == item.version,
            )
            .values(
                decision_state="approving",
                reviewer_id=actor_id,
                reviewed_at=now,
                decision_action="approve",
            )
        )
        return result.rowcount == 1

    async def reject(self, item, actor_id, now, reason):
        result = await self.session.execute(
            update(ReviewItemModel)
            .where(
                ReviewItemModel.id == item.id,
                ReviewItemModel.delivery_state == "confirmed",
                ReviewItemModel.decision_state == "pending",
                ReviewItemModel.version == item.version,
            )
            .values(
                decision_state="rejected",
                decision_action="reject",
                rejection_reason=reason,
                reviewer_id=actor_id,
                reviewed_at=now,
                version=item.version + 1,
            )
        )
        if result.rowcount != 1:
            return False
        # The terminal decision and publication ineligibility commit together.
        await self.session.execute(
            update(CatVideoSubmissionModel)
            .where(CatVideoSubmissionModel.id == item.submission_id)
            .values(status="rejected")
        )
        return True

    async def finish_approval(self, item, state, *, publication_id=None, error=None):
        await self.session.execute(
            update(ReviewItemModel)
            .where(
                ReviewItemModel.id == item.id,
                ReviewItemModel.decision_state == "approving",
                ReviewItemModel.version == item.version,
            )
            .values(
                decision_state=state,
                publication_id=publication_id,
                error_category=error,
                version=item.version + 1,
            )
        )
        return await self.get(item.id)

    async def recover_abandoned(self):
        await self.session.execute(
            update(ReviewItemModel)
            .where(ReviewItemModel.delivery_state == "sending")
            .values(delivery_state="unknown", error_category="review_delivery_unknown")
        )
        await self.session.execute(
            update(ReviewItemModel)
            .where(ReviewItemModel.decision_state == "approving")
            .values(
                decision_state="needs_reconciliation", error_category="review_approval_interrupted"
            )
        )
