"""SQLAlchemy repository implementations; transaction control stays in the UoW."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .entities import (
    CatPost,
    CatThread,
    CatVideoSubmission,
    MessagePurpose,
    SourceIdentity,
    TelegramMessageRef,
    TelegramProjection,
)
from .errors import (
    ConcurrentThreadUpdateError,
    CrossThreadParentError,
    DuplicatePostSubmissionError,
    DuplicateSourceMediaError,
    DuplicateTelegramMessageError,
    InvalidThreadStateError,
    MissingParentError,
    PostNotFoundError,
    SubmissionNotFoundError,
    ThreadNotFoundError,
)
from .models import (
    CatPostModel,
    CatThreadModel,
    CatVideoSubmissionModel,
    TelegramMessageRefModel,
)


def _new_id() -> str:
    return str(uuid4())


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _submission(model: CatVideoSubmissionModel) -> CatVideoSubmission:
    return CatVideoSubmission(
        id=model.id,
        source_provider=model.source_provider,
        source_media_id=model.source_media_id,
        source_channel_id=model.source_channel_id,
        thread_id=model.thread_id,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
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
        status: str = "pending",
    ) -> CatVideoSubmission:
        model = CatVideoSubmissionModel(
            id=_new_id(),
            source_provider=_required(source_provider, "source_provider").lower(),
            source_media_id=_required(source_media_id, "source_media_id"),
            source_channel_id=source_channel_id.strip() if source_channel_id else None,
            status=_required(status, "status"),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError as error:
            raise DuplicateSourceMediaError("Source media already exists") from error
        await self._session.refresh(model)
        return _submission(model)

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


class SqlAlchemyThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _source_query(self, source: SourceIdentity) -> Select[tuple[CatThreadModel]]:
        return select(CatThreadModel).where(
            CatThreadModel.source_provider == source.provider,
            CatThreadModel.source_channel_id == source.channel_id,
        )

    async def get_or_create(self, source: SourceIdentity) -> CatThread:
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
        if source.channel_name is not None and source.channel_name != model.source_channel_name:
            model.source_channel_name = source.channel_name
            changed = True
        if (
            source.channel_username is not None
            and source.channel_username != model.source_channel_username
        ):
            model.source_channel_username = source.channel_username
            changed = True
        if changed:
            await self._session.flush()
        await self._session.refresh(model)
        return _thread(model)

    async def get(self, thread_id: str) -> CatThread | None:
        model = await self._session.get(CatThreadModel, thread_id)
        return _thread(model) if model is not None else None

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
