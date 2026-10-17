"""Transactional graph placement; Telegram delivery is a separate application boundary."""

import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from ..persistence.contracts import PersistenceUnitOfWork
from ..persistence.entities import CatPost, CatThread, TelegramMessageRef
from ..persistence.errors import (
    ConcurrentThreadUpdateError,
    CrossThreadParentError,
    DuplicatePostSubmissionError,
    IntentConflictError,
    InvalidThreadStateError,
    MissingParentError,
    PostNotFoundError,
    ReplyTokenConflictError,
    SubmissionNotFoundError,
    ThreadNotFoundError,
)
from ..reply_tokens import EntryContractError, internal_id, new_reply_token, validate_reply_token
from .coordinator import ThreadCoordinator
from .entities import IssuedReplyToken, PlacedPost, PostIntent
from .errors import ReplyChainError

_PERSISTENCE_CODES = {
    ThreadNotFoundError: "reply_thread_not_found",
    SubmissionNotFoundError: "reply_submission_not_found",
    MissingParentError: "reply_parent_not_found",
    PostNotFoundError: "reply_parent_not_found",
    CrossThreadParentError: "reply_parent_cross_thread",
    IntentConflictError: "reply_intent_conflict",
    DuplicatePostSubmissionError: "reply_intent_conflict",
    InvalidThreadStateError: "reply_chain_invalid_state",
    ConcurrentThreadUpdateError: "reply_chain_conflict",
    ReplyTokenConflictError: "reply_token_invalid",
}


def token_digest(token: str) -> str:
    try:
        validate_reply_token(token)
    except EntryContractError:
        raise ReplyChainError("reply_token_invalid") from None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@asynccontextmanager
async def _boundary() -> AsyncIterator[None]:
    try:
        yield
    except ReplyChainError:
        raise
    except EntryContractError:
        raise ReplyChainError("reply_chain_invalid_state") from None
    except Exception as error:  # noqa: BLE001 - safe application persistence boundary
        code = _PERSISTENCE_CODES.get(type(error), "reply_chain_unavailable")
        raise ReplyChainError(code) from None


class ReplyChainService:
    def __init__(
        self,
        unit_of_work: Callable[[], PersistenceUnitOfWork],
        *,
        coordinator: ThreadCoordinator | None = None,
        destination_chat_id: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_factory: Callable[[], str] = new_reply_token,
    ) -> None:
        if destination_chat_id is not None and (
            type(destination_chat_id) is not int or destination_chat_id == 0
        ):
            raise ValueError("Expected numeric destination chat ID")
        self.unit_of_work = unit_of_work
        self.coordinator = coordinator or ThreadCoordinator()
        self.destination_chat_id = destination_chat_id
        self.clock = clock
        self._token_factory = token_factory

    def now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ReplyChainError("reply_chain_invalid_state")
        return now.astimezone(UTC)

    async def _thread(self, uow: PersistenceUnitOfWork, thread_id: str) -> CatThread:
        internal_id(thread_id)
        thread = await uow.threads.get(thread_id)
        if thread is None:
            raise ReplyChainError("reply_thread_not_found")
        if (thread.root_post_id is None) != (thread.tail_post_id is None):
            raise ReplyChainError("reply_chain_invalid_state")
        if thread.root_post_id is not None:
            root = await self._parent(uow, thread, thread.root_post_id)
            await self._parent(uow, thread, thread.tail_post_id)
            if root.parent_post_id is not None:
                raise ReplyChainError("reply_chain_invalid_state")
            await self._ancestry(uow, thread, thread.tail_post_id)
        return thread

    async def _ancestry(self, uow: PersistenceUnitOfWork, thread: CatThread, post_id: str) -> None:
        visited: set[str] = set()
        while True:
            if post_id in visited:
                raise ReplyChainError("reply_chain_invalid_state")
            visited.add(post_id)
            post = await self._parent(uow, thread, post_id)
            if post.parent_post_id is None:
                if post.id != thread.root_post_id:
                    raise ReplyChainError("reply_chain_invalid_state")
                return
            post_id = post.parent_post_id

    async def _submission(
        self, uow: PersistenceUnitOfWork, submission_id: str, thread: CatThread
    ) -> None:
        internal_id(submission_id)
        submission = await uow.submissions.get(submission_id)
        if submission is None:
            raise ReplyChainError("reply_submission_not_found")
        if submission.thread_id != thread.id:
            raise ReplyChainError("reply_parent_cross_thread")
        if submission.status != "validated" or submission.source_identity_status not in {
            "verified",
            "user_selected",
        }:
            raise ReplyChainError("reply_chain_invalid_state")
        if submission.source_provider != thread.source.provider or (
            submission.source_identity_status == "verified"
            and submission.source_channel_id != thread.source.channel_id
        ):
            raise ReplyChainError("reply_chain_invalid_state")
        if await uow.threads.get_post_for_submission(submission_id) is not None:
            raise ReplyChainError("reply_intent_conflict")

    async def _parent(
        self, uow: PersistenceUnitOfWork, thread: CatThread, parent_id: str
    ) -> CatPost:
        internal_id(parent_id)
        parent = await uow.threads.get_post(parent_id)
        if parent is None:
            raise ReplyChainError("reply_parent_not_found")
        if parent.thread_id != thread.id:
            raise ReplyChainError("reply_parent_cross_thread")
        return parent

    async def _projection(self, uow: PersistenceUnitOfWork, post_id: str) -> TelegramMessageRef:
        if self.destination_chat_id is None:
            raise ReplyChainError("reply_parent_unpublished")
        projection = await uow.projections.get_destination(
            post_id=post_id, chat_id=self.destination_chat_id
        )
        if projection is None:
            raise ReplyChainError("reply_parent_unpublished")
        return projection.reference

    async def create_normal_intent(self, submission_id: str, thread_id: str) -> PostIntent:
        async with _boundary():
            async with self.unit_of_work() as uow:
                thread = await self._thread(uow, thread_id)
                await self._submission(uow, submission_id, thread)
                intent = await uow.intents.create(
                    submission_id=submission_id,
                    thread_id=thread_id,
                    mode="normal_append",
                    selected_parent_post_id=None,
                )
            return intent

    async def create_interactive_intent(
        self, submission_id: str, thread_id: str, selected_parent_post_id: str
    ) -> PostIntent:
        async with _boundary():
            async with self.unit_of_work() as uow:
                thread = await self._thread(uow, thread_id)
                await self._submission(uow, submission_id, thread)
                if thread.root_post_id is None:
                    raise ReplyChainError("reply_chain_invalid_state")
                await self._parent(uow, thread, selected_parent_post_id)
                await self._ancestry(uow, thread, selected_parent_post_id)
                intent = await uow.intents.create(
                    submission_id=submission_id,
                    thread_id=thread_id,
                    mode="interactive_reply",
                    selected_parent_post_id=selected_parent_post_id,
                )
            return intent

    async def finalize_intent(
        self, intent_id: str, *, require_parent_projection: bool = False
    ) -> PlacedPost:
        async with _boundary():
            internal_id(intent_id)
            # Read only the immutable thread routing key before acquiring the lock.
            async with self.unit_of_work() as uow:
                intent = await uow.intents.get(intent_id)
                if intent is None:
                    raise ReplyChainError("reply_intent_not_found")
            async with self.coordinator.hold(intent.thread_id):
                async with self.unit_of_work() as uow:
                    intent = await uow.intents.get(intent_id)
                    if intent is None:
                        raise ReplyChainError("reply_intent_not_found")
                    thread = await self._thread(uow, intent.thread_id)
                    await self._submission(uow, intent.submission_id, thread)
                    normal = intent.mode == "normal_append"
                    if (normal and intent.selected_parent_post_id is not None) or (
                        not normal
                        and (
                            intent.mode != "interactive_reply"
                            or intent.selected_parent_post_id is None
                            or thread.root_post_id is None
                        )
                    ):
                        raise ReplyChainError("reply_chain_invalid_state")
                    parent_id = thread.tail_post_id if normal else intent.selected_parent_post_id
                    if parent_id is not None:
                        await self._parent(uow, thread, parent_id)
                        await self._ancestry(uow, thread, parent_id)
                        if require_parent_projection:
                            await self._projection(uow, parent_id)
                    post = await uow.threads.add_post(
                        thread_id=thread.id,
                        submission_id=intent.submission_id,
                        parent_post_id=parent_id,
                    )
                    if normal:
                        if thread.root_post_id is None:
                            await uow.threads.initialize_root(
                                thread_id=thread.id,
                                post_id=post.id,
                                expected_version=thread.version,
                            )
                        else:
                            await uow.threads.advance_tail(
                                thread_id=thread.id,
                                post_id=post.id,
                                expected_tail_id=parent_id,
                                expected_version=thread.version,
                            )
                return PlacedPost(post.id, thread.id, post.parent_post_id, normal)

    async def require_parent_projection(self, post_id: str) -> TelegramMessageRef | None:
        """#7 preflight: a root needs no reply coordinates; every child must have them."""
        async with _boundary():
            internal_id(post_id)
            async with self.unit_of_work() as uow:
                post = await uow.threads.get_post(post_id)
                if post is None:
                    raise ReplyChainError("reply_parent_not_found")
                thread = await self._thread(uow, post.thread_id)
                if post.parent_post_id is None:
                    if thread.root_post_id != post.id:
                        raise ReplyChainError("reply_chain_invalid_state")
                    return None
                await self._parent(uow, thread, post.parent_post_id)
                return await self._projection(uow, post.parent_post_id)

    async def issue_reply_token(
        self, post_id: str, *, expires_at: datetime | None = None
    ) -> IssuedReplyToken:
        async with _boundary():
            internal_id(post_id)
            now = self.now()
            if expires_at is not None and (expires_at.tzinfo is None or expires_at <= now):
                raise ReplyChainError("reply_token_invalid")
            token = self._token_factory()
            digest = token_digest(token)
            async with self.unit_of_work() as uow:
                post = await uow.threads.get_post(post_id)
                if post is None:
                    raise ReplyChainError("reply_parent_not_found")
                thread = await self._thread(uow, post.thread_id)
                if thread.root_post_id is None:
                    raise ReplyChainError("reply_chain_invalid_state")
                await self._ancestry(uow, thread, post.id)
                await self._projection(uow, post.id)
                await uow.reply_tokens.create(
                    token_digest=digest, post_id=post.id, created_at=now, expires_at=expires_at
                )
            return IssuedReplyToken(token, post_id, expires_at)

    async def revoke_reply_token(self, token: str) -> bool:
        async with _boundary():
            digest = token_digest(token)
            async with self.unit_of_work() as uow:
                return await uow.reply_tokens.revoke(digest, revoked_at=self.now())
