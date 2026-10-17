"""Shared SQLite/PostgreSQL domain, transaction and real-dispatcher contracts."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from sqlalchemy import event, func, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from cats_channel.persistence import Database, SourceIdentity, TelegramMessageRef
from cats_channel.persistence.models import (
    CatPostModel,
    PostIntentModel,
    ReplyEntryTokenModel,
)
from cats_channel.persistence.repositories import SqlAlchemyThreadRepository
from cats_channel.reply_chains.coordinator import ThreadCoordinator
from cats_channel.reply_chains.errors import ReplyChainError
from cats_channel.reply_chains.resolver import DatabaseReplyTargetResolver
from cats_channel.reply_chains.service import ReplyChainService, token_digest
from cats_channel.reply_tokens import ReplyTarget, new_reply_token

DESTINATION = -100123456789


@pytest.fixture(params=["sqlite", "postgres"])
async def chain_database(request, tmp_path):
    if request.param == "sqlite":
        database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'chains.sqlite3').as_posix()}")
        schema = None
    else:
        url = os.environ.get("CATS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("disposable PostgreSQL not configured")
        pytest.importorskip("asyncpg")
        parsed = make_url(url)
        assert os.environ.get("CATS_TEST_POSTGRES_DISPOSABLE") == "1"
        assert parsed.host in {"127.0.0.1", "localhost"}
        assert parsed.database == parsed.username == "cats_test"
        database = Database(url)
        schema = "reply_" + uuid4().hex
        async with database.engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await database.engine.dispose()

        @event.listens_for(database.engine.sync_engine, "connect")
        def set_schema(connection, _record):
            connection.run_async(lambda driver: driver.execute(f'SET search_path TO "{schema}"'))

    try:
        await database.create_schema_for_tests()
        yield database
    finally:
        if schema:
            async with database.engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await database.dispose()


async def seed(database, source="source", **updates):
    async with database.unit_of_work() as uow:
        thread = await uow.threads.get_or_create(SourceIdentity("youtube", source))
        values = {
            "source_provider": "youtube",
            "source_media_id": uuid4().hex,
            "source_channel_id": source,
            "source_identity_status": "verified",
            "thread_id": thread.id,
            "status": "validated",
        }
        values.update(updates)
        submission = await uow.submissions.create(**values)
    return thread, submission


def service(database, **kwargs):
    return ReplyChainService(database.unit_of_work, destination_chat_id=DESTINATION, **kwargs)


async def normal(database, chains, source="source"):
    thread, submission = await seed(database, source)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    return await chains.finalize_intent(intent.id)


async def project(database, post, message_id=1, chat_id=DESTINATION, purpose="destination"):
    async with database.unit_of_work() as uow:
        await uow.projections.add_for_post(
            post_id=post.post_id, purpose=purpose, reference=TelegramMessageRef(chat_id, message_id)
        )


async def allow_actor(actor_id, target):
    return actor_id == 42


def assert_code(caught, code):
    assert caught.value.code == str(caught.value) == code


async def test_root_linear_append_and_durable_exact_nested_branches(chain_database):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    assert root.parent_post_id is None and root.advances_tail
    thread, waiting = await seed(db)
    waiting_intent = await chains.create_normal_intent(waiting.id, thread.id)
    assert waiting_intent.selected_parent_post_id is None
    _, interactive = await seed(db)
    selected = await chains.create_interactive_intent(interactive.id, thread.id, root.post_id)
    second = await normal(db, chains)
    third = await chains.finalize_intent(waiting_intent.id)
    assert second.parent_post_id == root.post_id
    assert third.parent_post_id == second.post_id  # Tail selected at finalization, not intent.
    # A fresh service can recover the durable exact parent after the tail moved.
    branch = await service(db).finalize_intent(selected.id)
    _, nested_submission = await seed(db)
    nested_intent = await chains.create_interactive_intent(
        nested_submission.id, thread.id, branch.post_id
    )
    nested = await chains.finalize_intent(nested_intent.id)
    assert branch.parent_post_id == root.post_id and not branch.advances_tail
    assert nested.parent_post_id == branch.post_id and not nested.advances_tail
    async with db.unit_of_work() as uow:
        stored = await uow.threads.get(thread.id)
        assert stored.root_post_id == root.post_id
        assert stored.tail_post_id == third.post_id and stored.version == 3
        assert (await uow.intents.get(selected.id)).selected_parent_post_id == root.post_id
    with pytest.raises(ReplyChainError) as caught:
        await chains.finalize_intent(selected.id)
    assert_code(caught, "reply_intent_conflict")


async def test_source_rename_username_removal_and_interleaved_sources(chain_database):
    db = chain_database
    chains = service(db)
    first = await normal(db, chains, "one")
    second = await normal(db, chains, "two")
    await project(db, first, 1)
    await project(db, second, 2)
    async with db.unit_of_work() as uow:
        renamed = await uow.threads.get_or_create(SourceIdentity("youtube", "one", "New", "name"))
        removed = await uow.threads.get_or_create(SourceIdentity("youtube", "one", "New", None))
        assert renamed.id == removed.id == first.thread_id
        assert removed.source.channel_username is None
    next_one = await normal(db, chains, "one")
    next_two = await normal(db, chains, "two")
    assert next_one.parent_post_id == first.post_id
    assert next_two.parent_post_id == second.post_id
    assert next_one.thread_id != next_two.thread_id


@pytest.mark.parametrize(
    "case,code",
    [
        ("thread", "reply_thread_not_found"),
        ("submission", "reply_submission_not_found"),
        ("unvalidated", "reply_chain_invalid_state"),
        ("unresolved", "reply_chain_invalid_state"),
        ("wrong_thread", "reply_parent_cross_thread"),
        ("wrong_source", "reply_chain_invalid_state"),
    ],
)
async def test_invalid_submission_and_thread_rejected(chain_database, case, code):
    db = chain_database
    chains = service(db)
    updates = {"status": "pending"} if case == "unvalidated" else {}
    if case == "unresolved":
        updates["source_identity_status"] = "unresolved"
    if case == "wrong_source":
        updates["source_channel_id"] = "other"
    thread, submission = await seed(db, **updates)
    thread_id = str(uuid4()) if case == "thread" else thread.id
    if case == "wrong_thread":
        other, _ = await seed(db, "other")
        thread_id = other.id
    submission_id = str(uuid4()) if case == "submission" else submission.id
    with pytest.raises(ReplyChainError) as caught:
        await chains.create_normal_intent(submission_id, thread_id)
    assert_code(caught, code)


async def test_user_selected_unverified_source_uses_explicit_thread(chain_database):
    db = chain_database
    thread, submission = await seed(
        db, source_channel_id=None, source_identity_status="user_selected"
    )
    intent = await service(db).create_normal_intent(submission.id, thread.id)
    placed = await service(db).finalize_intent(intent.id)
    assert placed.thread_id == thread.id


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "reply_parent_not_found"),
        ("cross", "reply_parent_cross_thread"),
        ("empty", "reply_chain_invalid_state"),
    ],
)
async def test_invalid_interactive_parent(chain_database, case, code):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    thread, submission = await seed(db)
    parent = str(uuid4()) if case == "missing" else root.post_id
    if case == "cross":
        parent = (await normal(db, chains, "other")).post_id
    if case == "empty":
        thread, submission = await seed(db, "empty")
    with pytest.raises(ReplyChainError) as caught:
        await chains.create_interactive_intent(submission.id, thread.id, parent)
    assert_code(caught, code)


async def test_duplicate_intent_and_submission_reuse(chain_database):
    db = chain_database
    chains = service(db)
    thread, submission = await seed(db)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    with pytest.raises(ReplyChainError) as caught:
        await chains.create_normal_intent(submission.id, thread.id)
    assert_code(caught, "reply_intent_conflict")
    await chains.finalize_intent(intent.id)
    with pytest.raises(ReplyChainError) as caught:
        await chains.create_normal_intent(submission.id, thread.id)
    assert_code(caught, "reply_intent_conflict")


async def test_competing_normal_appends_are_linear(chain_database):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    intents = []
    for _ in range(2):
        thread, submission = await seed(db)
        intents.append(await chains.create_normal_intent(submission.id, thread.id))
    placed = await asyncio.wait_for(
        asyncio.gather(*(chains.finalize_intent(intent.id) for intent in intents)), 10
    )
    by_parent = {post.parent_post_id: post for post in placed}
    first = by_parent[root.post_id]
    last = by_parent[first.post_id]
    async with db.unit_of_work() as uow:
        assert (await uow.threads.get(root.thread_id)).tail_post_id == last.post_id
    assert chains.coordinator.pending_count == 0


async def test_competing_initial_posts_create_one_root(chain_database):
    db = chain_database
    chains = service(db)
    intents = []
    for _ in range(2):
        thread, submission = await seed(db)
        intents.append(await chains.create_normal_intent(submission.id, thread.id))
    results = await asyncio.wait_for(
        asyncio.gather(*(chains.finalize_intent(i.id) for i in intents)), 10
    )
    root = next(p for p in results if p.parent_post_id is None)
    child = next(p for p in results if p.parent_post_id is not None)
    assert child.parent_post_id == root.post_id
    async with db.unit_of_work() as uow:
        stored = await uow.threads.get(thread.id)
        assert (stored.root_post_id, stored.tail_post_id, stored.version) == (
            root.post_id,
            child.post_id,
            2,
        )


async def test_interactive_intent_rechecks_parent_after_waiting(chain_database):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    other = await normal(db, chains, "other")
    thread, submission = await seed(db)
    intent = await chains.create_interactive_intent(submission.id, thread.id, root.post_id)
    # Simulate a corrupted durable selection; finalize must not trust stored data blindly.
    async with db.engine.begin() as connection:
        await connection.execute(
            sql_update(PostIntentModel)
            .where(PostIntentModel.id == intent.id)
            .values(selected_parent_post_id=other.post_id)
        )
    with pytest.raises(ReplyChainError) as caught:
        await chains.finalize_intent(intent.id)
    assert_code(caught, "reply_parent_cross_thread")
    async with db.unit_of_work() as uow:
        assert await uow.threads.get_post_for_submission(submission.id) is None


async def test_stale_tail_cas_rolls_back_post_and_intent_remains_retryable(
    chain_database, monkeypatch
):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    thread, submission = await seed(db)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    advance = SqlAlchemyThreadRepository.advance_tail

    async def stale(self, **kwargs):
        kwargs["expected_version"] -= 1  # Simulated cross-process stale snapshot.
        return await advance(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyThreadRepository, "advance_tail", stale)
        with pytest.raises(ReplyChainError) as caught:
            await chains.finalize_intent(intent.id)
    assert_code(caught, "reply_chain_conflict")
    async with db.unit_of_work() as uow:
        assert await uow.threads.get_post_for_submission(submission.id) is None
        assert (await uow.threads.get(thread.id)).tail_post_id == root.post_id
        assert await uow.intents.get(intent.id) is not None
    assert (await chains.finalize_intent(intent.id)).parent_post_id == root.post_id


async def test_cancellation_rolls_back_and_releases_service_lock(chain_database, monkeypatch):
    db = chain_database
    chains = service(db)
    thread, submission = await seed(db)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    created = asyncio.Event()
    add_post = SqlAlchemyThreadRepository.add_post

    async def block_after_insert(self, **kwargs):
        await add_post(self, **kwargs)
        created.set()
        await asyncio.Event().wait()

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyThreadRepository, "add_post", block_after_insert)
        task = asyncio.create_task(chains.finalize_intent(intent.id))
        await asyncio.wait_for(created.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    assert chains.coordinator.pending_count == 0
    async with db.unit_of_work() as uow:
        assert await uow.threads.get_post_for_submission(submission.id) is None
    assert (await chains.finalize_intent(intent.id)).parent_post_id is None


async def test_repeated_cancellation_drains_rollback_before_releasing_lock(
    chain_database, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    db = chain_database
    chains = service(db)
    thread, submission = await seed(db)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    inserted, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    add_post, close = SqlAlchemyThreadRepository.add_post, AsyncSession.close

    async def block(self, **kwargs):
        await add_post(self, **kwargs)
        inserted.set()
        await asyncio.Event().wait()

    async def slow_close(self):
        # Only the mutating UoW reaches this after the insertion barrier.
        if inserted.is_set():
            closing.set()
            await release.wait()
        await close(self)

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyThreadRepository, "add_post", block)
        patch.setattr(AsyncSession, "close", slow_close)
        task = asyncio.create_task(chains.finalize_intent(intent.id))
        await asyncio.wait_for(inserted.wait(), 5)
        task.cancel()
        await asyncio.wait_for(closing.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and chains.coordinator.pending_count == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    assert chains.coordinator.pending_count == 0
    async with db.unit_of_work() as uow:
        assert await uow.threads.get_post_for_submission(submission.id) is None
    await chains.finalize_intent(intent.id)


async def test_different_thread_operations_can_overlap(chain_database, monkeypatch):
    db = chain_database
    chains = service(db)
    intents = []
    for source in ("one", "two"):
        thread, submission = await seed(db, source)
        intents.append(await chains.create_normal_intent(submission.id, thread.id))
    entered = set()
    both = asyncio.Event()
    add_post = SqlAlchemyThreadRepository.add_post

    async def rendezvous(self, **kwargs):
        entered.add(kwargs["thread_id"])
        if len(entered) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        return await add_post(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyThreadRepository, "add_post", rendezvous)
        # SQLite allows only one writer; overlap is proven before either write.
        results = await asyncio.gather(
            *(chains.finalize_intent(i.id) for i in intents), return_exceptions=True
        )
    assert len(entered) == 2 and chains.coordinator.pending_count == 0
    if db.engine.dialect.name == "postgresql":
        assert all(not isinstance(result, BaseException) for result in results)
    else:
        assert any(not isinstance(result, BaseException) for result in results)
        # A losing SQLite writer remains retryable, with no partial post.
        for intent, result in zip(intents, results, strict=True):
            if isinstance(result, ReplyChainError):
                await chains.finalize_intent(intent.id)


async def test_parent_projection_guard_and_tokens_fail_closed(chain_database):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    assert await chains.require_parent_projection(root.post_id) is None
    thread, submission = await seed(db)
    intent = await chains.create_normal_intent(submission.id, thread.id)
    with pytest.raises(ReplyChainError) as caught:
        await chains.finalize_intent(intent.id, require_parent_projection=True)
    assert_code(caught, "reply_parent_unpublished")
    with pytest.raises(ReplyChainError) as caught:
        await chains.issue_reply_token(root.post_id)
    assert_code(caught, "reply_parent_unpublished")
    await project(db, root, 1, purpose="private")
    await project(db, root, 2, chat_id=DESTINATION - 1)
    with pytest.raises(ReplyChainError):
        await chains.issue_reply_token(root.post_id)
    await project(db, root, 3)
    child = await chains.finalize_intent(intent.id, require_parent_projection=True)
    assert await chains.require_parent_projection(child.post_id) == TelegramMessageRef(
        DESTINATION, 3
    )


async def test_reusable_tokens_are_hashed_and_unknown_expired_revoked_denied_identically(
    chain_database, capsys
):
    db = chain_database
    now = datetime.now(UTC)
    chains = service(db, clock=lambda: now)
    root = await normal(db, chains)
    await project(db, root)
    issued = await chains.issue_reply_token(root.post_id, expires_at=now + timedelta(minutes=1))
    resolver = DatabaseReplyTargetResolver(chains, authorize_actor=allow_actor)
    target = ReplyTarget(root.post_id, root.thread_id)
    assert await resolver.resolve(issued.token, actor_id=42) == target
    assert await resolver.resolve(issued.token, actor_id=42) == target
    assert await resolver.resolve(issued.token, actor_id=99) is None
    assert await resolver.resolve("private malformed input", actor_id=42) is None
    assert await resolver.resolve(new_reply_token(), actor_id=42) is None
    async with db.unit_of_work() as uow:
        stored = await uow.reply_tokens.get(token_digest(issued.token))
        assert stored.post_id == root.post_id
        assert issued.token not in repr(stored) + repr(issued)
    async with db.engine.connect() as connection:
        row = (await connection.execute(select(ReplyEntryTokenModel))).first()
        assert issued.token not in str(row)
        assert token_digest(issued.token) in str(row)
    now += timedelta(minutes=1)
    assert await resolver.resolve(issued.token, actor_id=42) is None
    permanent = await chains.issue_reply_token(root.post_id)
    assert await resolver.resolve(permanent.token, actor_id=42) == target
    assert await chains.revoke_reply_token(permanent.token)
    assert not await chains.revoke_reply_token(permanent.token)
    assert await resolver.resolve(permanent.token, actor_id=42) is None
    captured = capsys.readouterr()
    assert issued.token not in captured.out + captured.err
    assert permanent.token not in captured.out + captured.err


async def test_token_denies_corrupt_cross_thread_or_missing_target(chain_database):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    other = await normal(db, chains, "other")
    await project(db, root)
    issued = await chains.issue_reply_token(root.post_id)
    resolver = DatabaseReplyTargetResolver(chains, authorize_actor=allow_actor)
    # Foreign keys prevent a token pointing at a missing post.
    with pytest.raises(IntegrityError):
        async with db.engine.begin() as connection:
            await connection.execute(sql_update(ReplyEntryTokenModel).values(post_id=str(uuid4())))
    # Even legacy/corrupt parent relationships never become an entry target.
    async with db.engine.begin() as connection:
        await connection.execute(
            sql_update(CatPostModel)
            .where(CatPostModel.id == root.post_id)
            .values(parent_post_id=other.post_id)
        )
    assert await resolver.resolve(issued.token, actor_id=42) is None


async def test_ambiguous_destination_projection_is_unavailable(chain_database):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    await project(db, root)
    issued = await chains.issue_reply_token(root.post_id)
    await project(db, root, 2)
    resolver = DatabaseReplyTargetResolver(chains, authorize_actor=allow_actor)
    assert await resolver.resolve(issued.token, actor_id=42) is None


async def test_real_dispatcher_uses_database_resolver_and_preserves_replacement(chain_database):
    from aiogram import Bot
    from test_bot_application import ADMIN_ID, BOT_TOKEN, RecordingSession, settings, update
    from test_bot_entry_contracts import context

    from cats_channel.bot import create_bot_application

    db = chain_database
    root = await normal(db, service(db))
    await project(db, root)
    issued = await service(db).issue_reply_token(root.post_id)
    session = RecordingSession()
    bot = Bot(BOT_TOKEN, session=session)
    app = create_bot_application(settings(), bot=bot, persistence_unit_of_work=db.unit_of_work)
    try:
        await app.dispatcher.feed_update(bot, update(f"/start catreply_{issued.token}"))
        state = context(app, bot)
        assert await state.get_data() == {
            "thread_id": root.thread_id,
            "parent_post_id": root.post_id,
        }
        await app.dispatcher.feed_update(bot, update("/cancel", update_id=2))
        assert await state.get_data() == {}
        # Slow real database resolution cannot overwrite a newer command.
        resolver = app.dispatcher.workflow_data["reply_target_resolver"]
        original = resolver._authorize_actor
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(actor, target):
            entered.set()
            await release.wait()
            return await original(actor, target)

        resolver._authorize_actor = delayed
        pending = asyncio.create_task(
            app.dispatcher.feed_update(bot, update(f"/start catreply_{issued.token}", update_id=3))
        )
        await asyncio.wait_for(entered.wait(), 5)
        await app.dispatcher.feed_update(bot, update("/cancel", update_id=4))
        release.set()
        await asyncio.wait_for(pending, 5)
        assert await state.get_data() == {}
        assert app.flow_coordinator.pending_count == 0
        assert ADMIN_ID == 42
    finally:
        await app.dispatcher.emit_shutdown()
        await session.close()


async def test_invalid_root_tail_state_is_rejected(chain_database, monkeypatch):
    db = chain_database
    chains = service(db)
    root = await normal(db, chains)
    thread, submission = await seed(db)
    get = SqlAlchemyThreadRepository.get

    async def inconsistent(self, thread_id):
        value = await get(self, thread_id)
        return replace(value, tail_post_id=None)

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyThreadRepository, "get", inconsistent)
        with pytest.raises(ReplyChainError) as caught:
            await chains.create_normal_intent(submission.id, thread.id)
    assert_code(caught, "reply_chain_invalid_state")
    assert root.post_id


async def test_database_mode_parent_and_one_intent_constraints(chain_database):
    db = chain_database
    thread, submission = await seed(db)
    with pytest.raises(IntegrityError):
        async with db.engine.begin() as connection:
            await connection.execute(
                PostIntentModel.__table__.insert().values(
                    id=str(uuid4()),
                    submission_id=submission.id,
                    thread_id=thread.id,
                    mode="interactive_reply",
                    selected_parent_post_id=None,
                )
            )
    intent = await service(db).create_normal_intent(submission.id, thread.id)
    async with db.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(PostIntentModel)) == 1
    assert intent.mode == "normal_append"


async def test_keyed_lock_cleans_cancelled_waiters_and_releases():
    coordinator = ThreadCoordinator()
    started = asyncio.Event()

    async def wait_same():
        started.set()
        async with coordinator.hold("one"):
            pytest.fail("cancelled waiter entered")

    async with coordinator.hold("one"):
        task = asyncio.create_task(wait_same())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with coordinator.hold("two"):
            assert coordinator.pending_count == 2
    assert coordinator.pending_count == 0


async def test_safe_failure_and_cancellation_boundaries(chain_database):
    @asynccontextmanager
    async def broken():
        raise RuntimeError("private token SQL payload")
        yield

    chains = ReplyChainService(broken)
    with pytest.raises(ReplyChainError) as caught:
        await chains.finalize_intent(str(uuid4()))
    assert_code(caught, "reply_chain_unavailable")
    assert caught.value.__suppress_context__
    assert (
        await DatabaseReplyTargetResolver(chains, authorize_actor=allow_actor).resolve(
            new_reply_token(), actor_id=42
        )
    ) is None

    @asynccontextmanager
    async def cancelled():
        raise asyncio.CancelledError
        yield

    resolver = DatabaseReplyTargetResolver(
        ReplyChainService(cancelled), authorize_actor=allow_actor
    )
    with pytest.raises(asyncio.CancelledError):
        await resolver.resolve(new_reply_token(), actor_id=42)
