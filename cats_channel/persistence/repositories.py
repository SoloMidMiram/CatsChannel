"""SQLAlchemy repository implementations; transaction control stays in the UoW."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..submission_provenance import submission_provenance_record
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
from .errors import (
    ConcurrentThreadUpdateError,
    CrossThreadParentError,
    DuplicateHandoffTokenError,
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
from .models import (
    CatPostModel,
    CatThreadModel,
    CatVideoSubmissionModel,
    MediaHandoffRequestModel,
    TelegramMessageRefModel,
)


def _new_id() -> str:
    return str(uuid4())


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _json_object(value: dict[str, object] | None, field: str) -> dict[str, object]:
    candidate = {} if value is None else value
    if not isinstance(candidate, dict) or not all(isinstance(key, str) for key in candidate):
        raise ValueError(f"{field} must be a JSON object")
    try:
        return json.loads(json.dumps(candidate, allow_nan=False))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must contain JSON values") from None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _submission(model: CatVideoSubmissionModel) -> CatVideoSubmission:
    return CatVideoSubmission(
        id=model.id,
        source_provider=model.source_provider,
        source_media_id=model.source_media_id,
        source_channel_id=model.source_channel_id,
        source_channel_name=model.source_channel_name,
        source_channel_username=model.source_channel_username,
        source_identity_status=model.source_identity_status,
        thread_id=model.thread_id,
        status=model.status,
        media_origin=model.media_origin,
        media_metadata=dict(model.media_metadata),
        validation_evidence=dict(model.validation_evidence),
        provenance=dict(model.provenance),
        created_at=model.created_at,
        updated_at=model.updated_at,
        placement_mode=model.placement_mode,
        selected_parent_post_id=model.selected_parent_post_id,
    )


def _handoff(model: MediaHandoffRequestModel) -> HandoffRequest:
    return HandoffRequest(
        id=model.id,
        actor_id=model.actor_id,
        conversation_chat_id=model.conversation_chat_id,
        operation=model.operation,
        expires_at=_utc(model.expires_at),
        consumed_at=_utc(model.consumed_at) if model.consumed_at is not None else None,
        submission_id=model.submission_id,
        created_at=_utc(model.created_at),
    )


def _thread(model: CatThreadModel) -> CatThread:
    return CatThread(
        id=model.id,
        source=SourceIdentity(
            provider=model.source_provider,
            channel_id=model.source_channel_id,
            channel_name=model.source_channel_name,
            channel_username=model.source_channel_username,
        ),
        root_post_id=model.root_post_id,
        tail_post_id=model.tail_post_id,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _post(model: CatPostModel) -> CatPost:
    return CatPost(
        id=model.id,
        submission_id=model.submission_id,
        thread_id=model.thread_id,
        parent_post_id=model.parent_post_id,
        created_at=model.created_at,
    )


def _projection(model: TelegramMessageRefModel) -> TelegramProjection:
    return TelegramProjection(
        id=model.id,
        purpose=model.purpose,  # type: ignore[arg-type] - database check constrains values
        reference=TelegramMessageRef(chat_id=model.chat_id, message_id=model.message_id),
        post_id=model.post_id,
        submission_id=model.submission_id,
        created_at=model.created_at,
    )


class SqlAlchemySubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
    ) -> CatVideoSubmission:
        if source_identity_status not in {"verified", "user_selected", "unresolved"}:
            raise ValueError("source_identity_status is invalid")
        if status not in {"pending", "validated"}:
            raise ValueError("status is invalid")
        if media_origin not in {"legacy", "local_library", "telegram_native"}:
            raise ValueError("media_origin is invalid")
        if placement_mode is None:
            if selected_parent_post_id is not None:
                raise ValueError("placement_mode is required for a selected parent")
        elif placement_mode == "normal_append":
            if selected_parent_post_id is not None:
                raise ValueError("normal placement cannot select a parent")
        elif placement_mode == "interactive_reply":
            if thread_id is None or selected_parent_post_id is None:
                raise ValueError("interactive placement requires a thread and parent")
            parent = await self._session.get(CatPostModel, selected_parent_post_id)
            if parent is None or parent.thread_id != thread_id:
                raise ThreadNotFoundError("Interactive placement target is invalid")
        else:
            raise ValueError("placement_mode is invalid")
        if thread_id is not None and await self._session.get(CatThreadModel, thread_id) is None:
            raise ThreadNotFoundError("Thread does not exist")
        model = CatVideoSubmissionModel(
            id=_new_id(),
            source_provider=_required(source_provider, "source_provider").lower(),
            source_media_id=_required(source_media_id, "source_media_id"),
            source_channel_id=_optional(source_channel_id),
            source_channel_name=_optional(source_channel_name),
            source_channel_username=_optional(source_channel_username),
            source_identity_status=source_identity_status,
            thread_id=thread_id,
            status=_required(status, "status"),
            media_origin=media_origin,
            media_metadata=_json_object(media_metadata, "media_metadata"),
            validation_evidence=_json_object(validation_evidence, "validation_evidence"),
            provenance=submission_provenance_record(provenance, media_origin),
            placement_mode=placement_mode,
            selected_parent_post_id=selected_parent_post_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError as error:
            existing = await self.get_by_source_media(model.source_provider, model.source_media_id)
            if existing is not None:
                raise DuplicateSourceMediaError("Source media already exists") from error
            raise PersistenceError("Submission persistence failed") from error
        await self._session.refresh(model)
        return _submission(model)

    async def get(self, submission_id: str) -> CatVideoSubmission | None:
        model = await self._session.get(CatVideoSubmissionModel, submission_id)
        return _submission(model) if model is not None else None

    async def lock(self, submission_id: str) -> None:
        # PostgreSQL locks this row through commit/rollback. SQLite retains its
        # transaction snapshot and rejects a competing stale snapshot write.
        await self._session.scalar(
            select(CatVideoSubmissionModel)
            .where(CatVideoSubmissionModel.id == submission_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_by_source_media(
        self, source_provider: str, source_media_id: str
    ) -> CatVideoSubmission | None:
        result = await self._session.scalar(
            select(CatVideoSubmissionModel).where(
                CatVideoSubmissionModel.source_provider
                == _required(source_provider, "source_provider").lower(),
                CatVideoSubmissionModel.source_media_id
                == _required(source_media_id, "source_media_id"),
            )
        )
        return _submission(result) if result is not None else None


class SqlAlchemyHandoffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        token_digest: str,
        actor_id: int,
        conversation_chat_id: int,
        operation: str,
        expires_at: datetime,
    ) -> HandoffRequest:
        if not re.fullmatch(r"[0-9a-f]{64}", token_digest):
            raise ValueError("token_digest must be a SHA-256 digest")
        if actor_id <= 0 or conversation_chat_id == 0:
            raise ValueError("handoff binding is invalid")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        model = MediaHandoffRequestModel(
            id=_new_id(),
            token_digest=token_digest,
            actor_id=actor_id,
            conversation_chat_id=conversation_chat_id,
            operation=_required(operation, "operation"),
            expires_at=expires_at.astimezone(UTC),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError as error:
            existing = await self._session.scalar(
                select(MediaHandoffRequestModel.id).where(
                    MediaHandoffRequestModel.token_digest == token_digest
                )
            )
            if existing is not None:
                raise DuplicateHandoffTokenError("Handoff token already exists") from error
            raise PersistenceError("Handoff persistence failed") from error
        await self._session.refresh(model)
        return _handoff(model)

    async def get_bound(
        self,
        *,
        token_digest: str,
        actor_id: int,
        conversation_chat_id: int,
        operation: str,
    ) -> HandoffRequest | None:
        model = await self._session.scalar(
            select(MediaHandoffRequestModel).where(
                MediaHandoffRequestModel.token_digest == token_digest,
                MediaHandoffRequestModel.actor_id == actor_id,
                MediaHandoffRequestModel.conversation_chat_id == conversation_chat_id,
                MediaHandoffRequestModel.operation == operation,
            )
        )
        return _handoff(model) if model is not None else None

    async def get_for_submission(self, submission_id: str) -> HandoffRequest | None:
        models = list(
            (
                await self._session.scalars(
                    select(MediaHandoffRequestModel).where(
                        MediaHandoffRequestModel.submission_id == submission_id
                    )
                )
            ).all()
        )
        return _handoff(models[0]) if len(models) == 1 else None

    async def consume(
        self,
        *,
        handoff_id: str,
        submission_id: str,
        consumed_at: datetime,
    ) -> bool:
        statement = (
            update(MediaHandoffRequestModel)
            .where(
                MediaHandoffRequestModel.id == handoff_id,
                MediaHandoffRequestModel.consumed_at.is_(None),
                MediaHandoffRequestModel.submission_id.is_(None),
                MediaHandoffRequestModel.expires_at > consumed_at,
            )
            .values(consumed_at=consumed_at, submission_id=submission_id)
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(statement)
        return result.rowcount == 1


class SqlAlchemyThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_post(self, post_id: str) -> CatPost | None:
        model = await self._session.get(CatPostModel, post_id)
        return _post(model) if model is not None else None

    async def get_post_for_submission(self, submission_id: str) -> CatPost | None:
        model = await self._session.scalar(
            select(CatPostModel).where(CatPostModel.submission_id == submission_id)
        )
        return _post(model) if model is not None else None

    def _source_query(self, source: SourceIdentity) -> Select[tuple[CatThreadModel]]:
        return select(CatThreadModel).where(
            CatThreadModel.source_provider == source.provider,
            CatThreadModel.source_channel_id == source.channel_id,
        )

    async def get_or_create(self, source: SourceIdentity) -> CatThread:
        """Select by stable identity and replace its current display metadata."""
        model = await self._session.scalar(self._source_query(source))
        if model is None:
            candidate = CatThreadModel(
                id=_new_id(),
                source_provider=source.provider,
                source_channel_id=source.channel_id,
                source_channel_name=source.channel_name,
                source_channel_username=source.channel_username,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(candidate)
                    await self._session.flush()
                model = candidate
            except IntegrityError:
                model = await self._session.scalar(self._source_query(source))
                if model is None:
                    raise
        changed = False
        if source.channel_name != model.source_channel_name:
            model.source_channel_name = source.channel_name
            changed = True
        if source.channel_username != model.source_channel_username:
            model.source_channel_username = source.channel_username
            changed = True
        if changed:
            await self._session.flush()
        await self._session.refresh(model)
        return _thread(model)

    async def get(self, thread_id: str) -> CatThread | None:
        model = await self._session.get(CatThreadModel, thread_id)
        return _thread(model) if model is not None else None

    async def list_sources(self, *, limit: int = 20) -> tuple[CatThread, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        models = (
            await self._session.scalars(
                select(CatThreadModel)
                .order_by(CatThreadModel.created_at, CatThreadModel.id)
                .limit(limit)
            )
        ).all()
        return tuple(_thread(model) for model in models)

    async def contains_post(self, thread_id: str, post_id: str) -> bool:
        model = await self._session.get(CatPostModel, post_id)
        return model is not None and model.thread_id == thread_id

    async def add_post(
        self,
        *,
        thread_id: str,
        submission_id: str,
        parent_post_id: str | None = None,
    ) -> CatPost:
        thread = await self._session.get(CatThreadModel, thread_id)
        if thread is None:
            raise ThreadNotFoundError("Thread does not exist")
        submission = await self._session.get(CatVideoSubmissionModel, submission_id)
        if submission is None:
            raise SubmissionNotFoundError("Submission does not exist")
        if submission.thread_id not in {None, thread_id}:
            raise CrossThreadParentError("Submission belongs to another thread")
        if parent_post_id is not None:
            parent = await self._session.get(CatPostModel, parent_post_id)
            if parent is None:
                raise MissingParentError("Parent post does not exist")
            if parent.thread_id != thread_id:
                raise CrossThreadParentError("Parent belongs to another thread")
        model = CatPostModel(
            id=_new_id(),
            submission_id=submission_id,
            thread_id=thread_id,
            parent_post_id=parent_post_id,
        )
        try:
            async with self._session.begin_nested():
                submission.thread_id = thread_id
                self._session.add(model)
                await self._session.flush()
        except IntegrityError as error:
            raise DuplicatePostSubmissionError("Submission already has a post") from error
        await self._session.refresh(model)
        return _post(model)

    async def _post_in_thread(self, thread_id: str, post_id: str) -> CatPostModel:
        post = await self._session.get(CatPostModel, post_id)
        if post is None:
            raise PostNotFoundError("Post does not exist")
        if post.thread_id != thread_id:
            raise CrossThreadParentError("Post belongs to another thread")
        return post

    async def initialize_root(
        self, *, thread_id: str, post_id: str, expected_version: int
    ) -> CatThread:
        post = await self._post_in_thread(thread_id, post_id)
        if post.parent_post_id is not None:
            raise InvalidThreadStateError("A root post cannot have a parent")
        statement = (
            update(CatThreadModel)
            .where(
                CatThreadModel.id == thread_id,
                CatThreadModel.version == expected_version,
                CatThreadModel.root_post_id.is_(None),
                CatThreadModel.tail_post_id.is_(None),
            )
            .values(
                root_post_id=post_id,
                tail_post_id=post_id,
                version=CatThreadModel.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(statement)
        if result.rowcount != 1:
            raise ConcurrentThreadUpdateError("Thread root changed concurrently")
        thread = await self._session.get(CatThreadModel, thread_id)
        if thread is None:
            raise ThreadNotFoundError("Thread does not exist")
        await self._session.refresh(thread)
        return _thread(thread)

    async def advance_tail(
        self,
        *,
        thread_id: str,
        post_id: str,
        expected_tail_id: str,
        expected_version: int,
    ) -> CatThread:
        post = await self._post_in_thread(thread_id, post_id)
        if post.parent_post_id != expected_tail_id:
            raise InvalidThreadStateError("New tail must be a child of the expected tail")
        statement = (
            update(CatThreadModel)
            .where(
                CatThreadModel.id == thread_id,
                CatThreadModel.version == expected_version,
                CatThreadModel.tail_post_id == expected_tail_id,
            )
            .values(tail_post_id=post_id, version=CatThreadModel.version + 1)
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(statement)
        if result.rowcount != 1:
            raise ConcurrentThreadUpdateError("Thread tail changed concurrently")
        thread = await self._session.get(CatThreadModel, thread_id)
        if thread is None:
            raise ThreadNotFoundError("Thread does not exist")
        await self._session.refresh(thread)
        return _thread(thread)


class SqlAlchemyProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_destination(self, *, post_id: str, chat_id: int) -> TelegramProjection | None:
        models = list(
            (
                await self._session.scalars(
                    select(TelegramMessageRefModel).where(
                        TelegramMessageRefModel.post_id == post_id,
                        TelegramMessageRefModel.purpose == "destination",
                        TelegramMessageRefModel.chat_id == chat_id,
                    )
                )
            ).all()
        )
        # Ambiguous legacy mappings must not silently choose a publication target.
        if len(models) != 1:
            return None
        return _projection(models[0])

    async def _add(
        self,
        *,
        purpose: MessagePurpose,
        reference: TelegramMessageRef,
        post_id: str | None,
        submission_id: str | None,
    ) -> TelegramProjection:
        model = TelegramMessageRefModel(
            id=_new_id(),
            purpose=purpose,
            chat_id=reference.chat_id,
            message_id=reference.message_id,
            post_id=post_id,
            submission_id=submission_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError as error:
            raise DuplicateTelegramMessageError("Telegram coordinates already exist") from error
        await self._session.refresh(model)
        return _projection(model)

    async def add_for_post(
        self, *, post_id: str, purpose: MessagePurpose, reference: TelegramMessageRef
    ) -> TelegramProjection:
        if await self._session.get(CatPostModel, post_id) is None:
            raise PostNotFoundError("Post does not exist")
        return await self._add(
            purpose=purpose,
            reference=reference,
            post_id=post_id,
            submission_id=None,
        )

    async def add_for_submission(
        self,
        *,
        submission_id: str,
        purpose: MessagePurpose,
        reference: TelegramMessageRef,
    ) -> TelegramProjection:
        if await self._session.get(CatVideoSubmissionModel, submission_id) is None:
            raise SubmissionNotFoundError("Submission does not exist")
        return await self._add(
            purpose=purpose,
            reference=reference,
            post_id=None,
            submission_id=submission_id,
        )

    async def get_by_reference(self, reference: TelegramMessageRef) -> TelegramProjection | None:
        model = await self._session.scalar(
            select(TelegramMessageRefModel).where(
                TelegramMessageRefModel.chat_id == reference.chat_id,
                TelegramMessageRefModel.message_id == reference.message_id,
            )
        )
        return _projection(model) if model is not None else None
