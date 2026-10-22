"""Flush-only durable delivery repository with optimistic ownership checks."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..publication.entities import Attempt, Publication, validate_transition
from ..publication.errors import PublicationError
from .models import PublicationAttemptModel, PublicationModel, ReplyEntryTokenModel
from .repositories import _utc


def _publication(model):
    return Publication(
        model.id,
        model.post_id,
        model.destination_chat_id,
        model.state,
        model.version,
        model.current_attempt_id,
        model.error_category,
        model.markup_status,
        model.markup_token_digest,
        model.navigation_post_id,
        _utc(model.created_at),
        _utc(model.updated_at),
    )


def _attempt(model):
    return Attempt(
        model.id,
        model.publication_id,
        model.number,
        model.claim_token,
        _utc(model.started_at),
        _utc(model.completed_at) if model.completed_at else None,
        model.outcome,
        model.error_category,
        model.recovery,
    )


class SqlAlchemyPublicationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, publication_id):
        model = await self._session.get(PublicationModel, publication_id, populate_existing=True)
        return _publication(model) if model else None

    async def get_for_post(self, post_id, chat_id):
        model = await self._session.scalar(
            select(PublicationModel)
            .where(
                PublicationModel.post_id == post_id, PublicationModel.destination_chat_id == chat_id
            )
            .execution_options(populate_existing=True)
        )
        return _publication(model) if model else None

    async def create(self, post_id, chat_id):
        model = PublicationModel(id=str(uuid4()), post_id=post_id, destination_chat_id=chat_id)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _publication(model)

    async def _cas(self, publication, state, **values):
        validate_transition(publication.state, state)
        result = await self._session.execute(
            update(PublicationModel)
            .where(
                PublicationModel.id == publication.id,
                PublicationModel.version == publication.version,
                PublicationModel.state == publication.state,
                PublicationModel.current_attempt_id == publication.current_attempt_id,
            )
            .values(state=state, version=publication.version + 1, **values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise PublicationError("publication_conflict")
        return await self.get(publication.id)

    async def transition(self, publication, state, *, category=None):
        # Owned outcomes must go through finish, never a bare transition.
        if publication.state in {"sending", "unknown"} or state == "sending":
            raise PublicationError("publication_transition_invalid")
        return await self._cas(publication, state, error_category=category)

    async def claim(self, publication, now: datetime):
        if publication.state != "pending":
            raise PublicationError("publication_conflict")
        number = (
            await self._session.scalar(
                select(func.max(PublicationAttemptModel.number)).where(
                    PublicationAttemptModel.publication_id == publication.id
                )
            )
            or 0
        ) + 1
        model = PublicationAttemptModel(
            id=str(uuid4()),
            publication_id=publication.id,
            number=number,
            claim_token=str(uuid4()),
            started_at=now,
        )
        await self._cas(publication, "sending", current_attempt_id=model.id, error_category=None)
        self._session.add(model)
        await self._session.flush()
        return _attempt(model)

    async def current_attempt(self, publication):
        model = await self._session.get(PublicationAttemptModel, publication.current_attempt_id)
        return _attempt(model) if model else None

    async def finish(self, publication, attempt, state, now, *, category=None, recovery=None):
        if attempt.publication_id != publication.id or attempt.id != publication.current_attempt_id:
            raise PublicationError("publication_conflict")
        result = await self._session.execute(
            update(PublicationAttemptModel)
            .where(
                PublicationAttemptModel.id == attempt.id,
                PublicationAttemptModel.publication_id == publication.id,
                PublicationAttemptModel.claim_token == attempt.claim_token,
                PublicationAttemptModel.outcome
                == ("unknown" if publication.state == "unknown" else None),
            )
            .values(outcome=state, completed_at=now, error_category=category, recovery=recovery)
        )
        if result.rowcount != 1:
            raise PublicationError("publication_conflict")
        return await self._cas(publication, state, error_category=category)

    async def list_sending(self):
        return tuple(
            _publication(m)
            for m in await self._session.scalars(
                select(PublicationModel).where(PublicationModel.state == "sending")
            )
        )

    async def set_markup(self, publication_id, status):
        if status not in {"pending", "installed", "failed"}:
            raise PublicationError("publication_transition_invalid")
        await self._session.execute(
            update(PublicationModel)
            .where(PublicationModel.id == publication_id, PublicationModel.state == "confirmed")
            .values(markup_status=status)
        )

    async def replace_token(self, publication_id, digest):
        publication = await self.get(publication_id)
        if publication is None or publication.state != "confirmed":
            raise PublicationError("publication_transition_invalid")
        if publication.markup_token_digest:
            await self._session.execute(
                delete(ReplyEntryTokenModel).where(
                    ReplyEntryTokenModel.token_digest == publication.markup_token_digest,
                    ReplyEntryTokenModel.post_id == publication.post_id,
                )
            )
        await self._session.execute(
            update(PublicationModel)
            .where(PublicationModel.id == publication_id)
            .values(markup_token_digest=digest, markup_status="pending")
        )

    async def set_navigation(self, publication_id, child_post_id):
        await self._session.execute(
            update(PublicationModel)
            .where(PublicationModel.id == publication_id, PublicationModel.state == "confirmed")
            .values(navigation_post_id=child_post_id, markup_status="pending")
        )
