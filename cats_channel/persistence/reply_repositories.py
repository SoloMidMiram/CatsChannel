"""Durable immutable placement intents and hashed, revocable reply tokens."""

import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..reply_chains.entities import PlacementMode, PostIntent, ReplyEntryToken
from ..reply_tokens import internal_id
from .errors import (
    CrossThreadParentError,
    IntentConflictError,
    MissingParentError,
    ReplyTokenConflictError,
    SubmissionNotFoundError,
    ThreadNotFoundError,
)
from .models import (
    CatPostModel,
    CatThreadModel,
    CatVideoSubmissionModel,
    PostIntentModel,
    ReplyEntryTokenModel,
)
from .repositories import _new_id, _utc


def _intent(model: PostIntentModel) -> PostIntent:
    return PostIntent(
        model.id,
        model.submission_id,
        model.thread_id,
        model.mode,
        model.selected_parent_post_id,
        _utc(model.created_at),
    )


def _token(model: ReplyEntryTokenModel) -> ReplyEntryToken:
    return ReplyEntryToken(
        model.token_digest,
        model.post_id,
        _utc(model.created_at),
        _utc(model.expires_at) if model.expires_at else None,
        _utc(model.revoked_at) if model.revoked_at else None,
    )


def _write_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reply token dates must be timezone-aware")
    return value.astimezone(UTC)


class SqlAlchemyIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        submission_id: str,
        thread_id: str,
        mode: PlacementMode,
        selected_parent_post_id: str | None,
    ) -> PostIntent:
        internal_id(submission_id)
        internal_id(thread_id)
        if mode not in {"normal_append", "interactive_reply"} or (
            (mode == "normal_append") != (selected_parent_post_id is None)
        ):
            raise IntentConflictError("Invalid intent mode/parent")
        submission = await self._session.get(CatVideoSubmissionModel, submission_id)
        if submission is None:
            raise SubmissionNotFoundError("Submission does not exist")
        if await self._session.get(CatThreadModel, thread_id) is None:
            raise ThreadNotFoundError("Thread does not exist")
        if submission.thread_id != thread_id:
            raise CrossThreadParentError("Submission belongs to another thread")
        if selected_parent_post_id is not None:
            internal_id(selected_parent_post_id)
            parent = await self._session.get(CatPostModel, selected_parent_post_id)
            if parent is None:
                raise MissingParentError("Parent does not exist")
            if parent.thread_id != thread_id:
                raise CrossThreadParentError("Parent belongs to another thread")
        model = PostIntentModel(
            id=_new_id(),
            submission_id=submission_id,
            thread_id=thread_id,
            mode=mode,
            selected_parent_post_id=selected_parent_post_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            raise IntentConflictError("Intent already exists or is invalid") from None
        await self._session.refresh(model)
        return _intent(model)

    async def get(self, intent_id: str) -> PostIntent | None:
        model = await self._session.get(PostIntentModel, intent_id)
        return _intent(model) if model is not None else None

    async def get_for_submission(self, submission_id: str) -> PostIntent | None:
        internal_id(submission_id)
        model = await self._session.scalar(
            select(PostIntentModel).where(PostIntentModel.submission_id == submission_id)
        )
        return _intent(model) if model is not None else None


class SqlAlchemyReplyTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        token_digest: str,
        post_id: str,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> ReplyEntryToken:
        internal_id(post_id)
        if not re.fullmatch(r"[0-9a-f]{64}", token_digest):
            raise ValueError("Invalid reply digest")
        created_at = _write_utc(created_at)
        expires_at = _write_utc(expires_at) if expires_at is not None else None
        if expires_at is not None and expires_at <= created_at:
            raise ValueError("Invalid reply token dates")
        model = ReplyEntryTokenModel(
            token_digest=token_digest, post_id=post_id, created_at=created_at, expires_at=expires_at
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            raise ReplyTokenConflictError(
                "Reply token already exists or target is invalid"
            ) from None
        await self._session.refresh(model)
        return _token(model)

    async def get(self, token_digest: str) -> ReplyEntryToken | None:
        model = await self._session.get(ReplyEntryTokenModel, token_digest)
        return _token(model) if model is not None else None

    async def revoke(self, token_digest: str, *, revoked_at: datetime) -> bool:
        revoked_at = _write_utc(revoked_at)
        result = await self._session.execute(
            update(ReplyEntryTokenModel)
            .where(
                ReplyEntryTokenModel.token_digest == token_digest,
                ReplyEntryTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        return result.rowcount == 1
