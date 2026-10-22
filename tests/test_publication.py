"""Offline delivery incidents and graph invariants on SQLite and disposable PostgreSQL."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from test_reply_chains import DESTINATION, seed
from test_reply_chains import chain_database as _chain_database

from cats_channel.persistence import TelegramMessageRef
from cats_channel.persistence.database import SqlAlchemyUnitOfWork
from cats_channel.persistence.models import (
    ReplyEntryTokenModel,
    TelegramMessageRefModel,
)
from cats_channel.publication.entities import validate_transition
from cats_channel.publication.errors import DeliveryRejected, PublicationError
from cats_channel.publication.service import PublicationService
from cats_channel.reply_chains.service import ReplyChainService

chain_database = _chain_database

NOW = datetime(2026, 10, 22, tzinfo=UTC)


async def test_delivery_logs_are_allowlisted_and_secret_safe(chain_database, caplog):
    import json
    import logging

    service = publisher(chain_database, logger=logging.getLogger("publication_test"))
    submission, _ = await pending(chain_database, service)
    service.transport.error = TimeoutError("token=SECRET file_id=PRIVATE caption=BODY")
    with caplog.at_level(logging.INFO, logger="publication_test"):
        result = await service.approve_pilot(submission.id)
    assert result.state == "unknown"
    logs = [json.loads(r.message) for r in caplog.records if r.name == "publication_test"]
    events = [r for r in logs if r["event"] == "publication_stage"]
    assert [(r["phase"], r["state"], r["attempt_number"]) for r in events] == [
        ("dispatch", "sending", 1),
        ("outcome", "unknown", 1),
    ]
    assert events[-1]["recovery_action"] == "operator_required"
    assert not any(secret in caplog.text for secret in ["SECRET", "PRIVATE", "BODY", "claim_token"])


class Transport:
    def __init__(self):
        self.sends = []
        self.markup = []
        self.error = None
        self.markup_error = False
        self.started = self.release = None

    async def send(self, submission, *, parent):
        self.sends.append((submission.id, parent))
        if self.started:
            self.started.set()
            await self.release.wait()
        if self.error:
            raise self.error
        return TelegramMessageRef(DESTINATION, len(self.sends))

    async def install_markup(self, reference, *, token, child):
        self.markup.append((reference, token, child))
        if self.markup_error:
            raise TimeoutError("private payload")


def publisher(db, transport=None, **kwargs):
    chains = ReplyChainService(db.unit_of_work, destination_chat_id=DESTINATION)
    return PublicationService(
        db.unit_of_work,
        reply_chains=chains,
        transport=transport or Transport(),
        destination_chat_id=DESTINATION,
        clock=lambda: NOW,
        **kwargs,
    )


async def pending(db, service, source="A", parent=None, cross_provider=False):
    updates = (
        {"source_provider": "telegram", "source_identity_status": "unresolved"}
        if cross_provider
        else {}
    )
    thread, submission = await seed(db, source, **updates)
    if parent:
        intent = await service.chains.create_interactive_intent(submission.id, thread.id, parent)
    else:
        intent = await service.chains.create_normal_intent(submission.id, thread.id)
    return submission, intent


async def test_roots_linear_older_nested_interleaved_and_truthful_provenance(chain_database):
    db = chain_database
    service = publisher(db)
    a1, _ = await pending(db, service)
    p1 = await service.approve_pilot(a1.id)
    a2, _ = await pending(db, service)
    p2 = await service.approve_pilot(a2.id)
    b1, _ = await pending(db, service, "B")
    pb = await service.approve_pilot(b1.id)
    x, _ = await pending(db, service, parent=p1.post_id, cross_provider=True)
    px = await service.approve_pilot(x.id)
    y, _ = await pending(db, service, parent=px.post_id)
    py = await service.approve_pilot(y.id)
    a3, _ = await pending(db, service)
    p3 = await service.approve_pilot(a3.id)
    assert all(
        p.state == "confirmed" and p.markup_status == "installed" for p in [p1, p2, pb, px, py, p3]
    )
    assert [parent.message_id if parent else None for _, parent in service.transport.sends] == [
        None,
        1,
        None,
        1,
        4,
        2,
    ]
    async with db.unit_of_work() as uow:
        post = await uow.threads.get_post(p3.post_id)
        assert (await uow.threads.get(post.thread_id)).tail_post_id == p3.post_id
        assert (await uow.submissions.get(x.id)).source_provider == "telegram"
        assert (await uow.submissions.get(x.id)).source_identity_status == "unresolved"
    # Both older-parent and nested branch navigation resolve confirmed references.
    assert any(
        ref.message_id == 1 and child and child.message_id == 4
        for ref, _, child in service.transport.markup
    )
    assert any(
        ref.message_id == 4 and child and child.message_id == 5
        for ref, _, child in service.transport.markup
    )


async def test_blocked_child_unblocks_and_does_not_block_other_source(chain_database):
    db = chain_database
    service = publisher(db)
    root, intent = await pending(db, service)
    await service.chains.finalize_intent(intent.id)  # crash before publication creation
    child, _ = await pending(db, service)
    blocked = await service.approve_pilot(child.id)
    assert blocked.state == "blocked" and service.transport.sends == []
    other, _ = await pending(db, service, "B")
    assert (await service.approve_pilot(other.id)).state == "confirmed"
    assert (await service.approve_pilot(root.id)).state == "confirmed"
    assert (await service.approve_pilot(child.id)).state == "confirmed"


async def test_existing_legacy_projection_requires_review_without_resending(chain_database):
    db = chain_database
    service = publisher(db)
    submission, intent = await pending(db, service)
    post = await service.chains.finalize_intent(intent.id)
    reference = TelegramMessageRef(DESTINATION, 77)
    async with db.unit_of_work() as uow:
        await uow.projections.add_for_post(
            post_id=post.post_id, purpose="destination", reference=reference
        )
    result = await service.approve_pilot(submission.id)
    assert result.state == "unknown" and result.error_category == "existing_projection_review"
    assert not service.transport.sends
    with pytest.raises(PublicationError, match="delivery_coordinates_conflict"):
        await service.reconcile(result.id, reference=TelegramMessageRef(DESTINATION, 78))
    assert (await service.reconcile(result.id, reference=reference)).state == "confirmed"
    assert not service.transport.sends


@pytest.mark.parametrize(
    "error,state",
    [(DeliveryRejected(), "failed"), (TimeoutError(), "unknown"), (ConnectionError(), "unknown")],
)
async def test_failures_never_implicitly_retry(chain_database, error, state):
    service = publisher(chain_database)
    submission, _ = await pending(chain_database, service)
    service.transport.error = error
    result = await service.approve_pilot(submission.id)
    assert result.state == state
    assert (await service.approve_pilot(submission.id)).state == state
    assert len(service.transport.sends) == 1
    with pytest.raises(PublicationError):
        if state == "unknown":
            await service.requeue_failed(result.id)
        else:
            await service.reconcile(result.id, non_delivery_proven=True)


async def test_duplicate_requests_serialized_and_confirmed_never_resends(chain_database):
    db = chain_database
    transport = Transport()
    service = publisher(db, transport)
    second_service = publisher(db, transport, coordinator=service.coordinator)
    submission, _ = await pending(db, service)
    transport.started, transport.release = asyncio.Event(), asyncio.Event()
    first = asyncio.create_task(service.approve_pilot(submission.id))
    await asyncio.wait_for(transport.started.wait(), 5)
    # Inspect durable attempt through a fresh connection while transport is paused.
    async with db.unit_of_work() as uow:
        post = await uow.threads.get_post_for_submission(submission.id)
        stored = await uow.publications.get_for_post(post.id, DESTINATION)
        assert stored.state == "sending"
        assert (await uow.publications.current_attempt(stored)).number == 1
    second = asyncio.create_task(second_service.approve_pilot(submission.id))
    transport.release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), 10)
    assert results[0].id == results[1].id
    await publisher(db, transport).approve_pilot(submission.id)  # fresh process-like service
    assert len(transport.sends) == 1
    assert service.coordinator.pending_count == 0


async def test_database_cas_rejects_stale_claim_and_enforces_uniqueness(chain_database):
    db = chain_database
    service = publisher(db)
    submission, intent = await pending(db, service)
    post = await service.chains.finalize_intent(intent.id)
    async with db.unit_of_work() as uow:
        publication = await uow.publications.create(post.post_id, DESTINATION)
    async with db.unit_of_work() as uow:
        await uow.publications.claim(publication, NOW)
    with pytest.raises(PublicationError, match="publication_conflict"):
        async with db.unit_of_work() as uow:
            await uow.publications.claim(publication, NOW)
    with pytest.raises(IntegrityError):
        async with db.unit_of_work() as uow:
            await uow.publications.create(post.post_id, DESTINATION)
    assert (await service.approve_pilot(submission.id)).state == "sending"
    assert not service.transport.sends


async def test_cancel_dispatch_persists_unknown_and_propagates(chain_database):
    service = publisher(chain_database)
    submission, _ = await pending(chain_database, service)
    transport = service.transport
    transport.started, transport.release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(service.approve_pilot(submission.id))
    await asyncio.wait_for(transport.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    assert (await service.approve_pilot(submission.id)).state == "unknown"
    assert len(transport.sends) == 1 and service.coordinator.pending_count == 0


async def test_restart_abandoned_attempt_and_operator_reconciliation(chain_database):
    db = chain_database
    service = publisher(db)
    submission, intent = await pending(db, service)
    post = await service.chains.finalize_intent(intent.id)
    async with db.unit_of_work() as uow:
        publication = await uow.publications.create(post.post_id, DESTINATION)
        await uow.publications.claim(publication, NOW)
    restarted = publisher(db)
    await restarted.recover_abandoned()
    assert (await restarted.approve_pilot(submission.id)).state == "unknown"
    assert not restarted.transport.sends
    result = await restarted.reconcile(
        publication.id, reference=TelegramMessageRef(DESTINATION, 77)
    )
    assert result.state == "confirmed" and result.markup_status == "installed"
    assert not restarted.transport.sends
    async with db.unit_of_work() as uow:
        assert (await uow.threads.get(post.thread_id)).tail_post_id == post.post_id


async def test_reconciliation_rejects_changed_destination_without_writing(chain_database):
    db = chain_database
    original = publisher(db)
    submission, _ = await pending(db, original)
    original.transport.error = TimeoutError()
    unknown = await original.approve_pilot(submission.id)
    changed_destination = DESTINATION - 1
    changed = PublicationService(
        db.unit_of_work,
        reply_chains=ReplyChainService(db.unit_of_work, destination_chat_id=changed_destination),
        transport=Transport(),
        destination_chat_id=changed_destination,
        clock=lambda: NOW,
    )

    with pytest.raises(PublicationError, match="delivery_coordinates_conflict"):
        await changed.reconcile(
            unknown.id,
            reference=TelegramMessageRef(changed_destination, 77),
        )

    async with db.unit_of_work() as uow:
        stored = await uow.publications.get(unknown.id)
        assert stored is not None and stored.state == "unknown"
        assert (
            await uow.projections.get_destination(
                post_id=unknown.post_id, chat_id=changed_destination
            )
            is None
        )
        assert (
            await uow.projections.get_destination(post_id=unknown.post_id, chat_id=DESTINATION)
            is None
        )


async def test_proven_non_delivery_allows_only_explicit_retry(chain_database):
    service = publisher(chain_database)
    submission, _ = await pending(chain_database, service)
    service.transport.error = TimeoutError()
    unknown = await service.approve_pilot(submission.id)
    assert (await service.reconcile(unknown.id, non_delivery_proven=True)).state == "failed"
    assert (await service.approve_pilot(submission.id)).state == "failed"
    await service.requeue_failed(unknown.id)
    service.transport.error = None
    assert (await service.approve_pilot(submission.id)).state == "confirmed"
    async with chain_database.unit_of_work() as uow:
        result = await uow.publications.get(unknown.id)
        assert (await uow.publications.current_attempt(result)).number == 2


async def test_commit_failure_after_send_rolls_back_confirmation_and_retains_unknown(
    chain_database, monkeypatch
):
    db = chain_database
    service = publisher(db)
    submission, _ = await pending(db, service)
    original = SqlAlchemyUnitOfWork.__aexit__
    failed = False

    async def fail_confirmation_commit(self, exc_type, exc_value, traceback):
        nonlocal failed
        if not failed and exc_type is None:
            count = await self._session.scalar(
                select(func.count())
                .select_from(TelegramMessageRefModel)
                .where(TelegramMessageRefModel.purpose == "destination")
            )
            if count:
                failed = True
                error = RuntimeError("commit failed after external success")
                await original(self, RuntimeError, error, None)
                raise error
        return await original(self, exc_type, exc_value, traceback)

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "__aexit__", fail_confirmation_commit)
    result = await service.approve_pilot(submission.id)
    assert failed and result.state == "unknown" and len(service.transport.sends) == 1
    async with db.unit_of_work() as uow:
        assert (
            await uow.projections.get_destination(post_id=result.post_id, chat_id=DESTINATION)
            is None
        )
    assert (await service.approve_pilot(submission.id)).state == "unknown"


async def test_markup_repair_rotates_one_managed_token_and_never_resends(chain_database):
    db = chain_database
    service = publisher(db)
    service.transport.markup_error = True
    submission, _ = await pending(db, service)
    result = await service.approve_pilot(submission.id)
    assert result.state == "confirmed" and result.markup_status == "failed"
    for _ in range(3):
        await service.repair_markup(result.id)
    service.transport.markup_error = False
    result = await publisher(db, service.transport).repair_markup(result.id)
    assert result.markup_status == "installed" and len(service.transport.sends) == 1
    async with db.unit_of_work() as uow:
        # Token issuance and replacement belong to the same transaction.
        assert await uow.reply_tokens.get(result.markup_token_digest) is not None
    async with db.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(ReplyEntryTokenModel)) == 1


async def test_missing_parent_projection_blocks_without_reparenting(chain_database):
    db = chain_database
    service = publisher(db)
    root, _ = await pending(db, service)
    publication = await service.approve_pilot(root.id)
    async with db.engine.begin() as connection:
        await connection.execute(
            delete(TelegramMessageRefModel).where(
                TelegramMessageRefModel.post_id == publication.post_id
            )
        )
    child, _ = await pending(db, service)
    assert (await service.approve_pilot(child.id)).state == "blocked"
    assert len(service.transport.sends) == 1


@pytest.mark.parametrize(
    "before,after",
    [
        ("confirmed", "pending"),
        ("unknown", "sending"),
        ("sending", "pending"),
        ("failed", "confirmed"),
    ],
)
def test_illegal_transitions(before, after):
    with pytest.raises(PublicationError):
        validate_transition(before, after)


async def test_confirmation_projection_unique_per_destination(chain_database):
    db = chain_database
    service = publisher(db)
    submission, _ = await pending(db, service)
    result = await service.approve_pilot(submission.id)
    from cats_channel.persistence.errors import DuplicateTelegramMessageError

    with pytest.raises(DuplicateTelegramMessageError):
        async with db.unit_of_work() as uow:
            await uow.projections.add_for_post(
                post_id=result.post_id,
                purpose="destination",
                reference=TelegramMessageRef(DESTINATION, 999),
            )


async def test_postgres_competing_claims_use_database_cas(chain_database):
    db = chain_database
    if db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrent writer contract; SQLite stale CAS covered separately")
    service = publisher(db)
    _, intent = await pending(db, service)
    post = await service.chains.finalize_intent(intent.id)
    async with db.unit_of_work() as uow:
        publication = await uow.publications.create(post.post_id, DESTINATION)
    ready = asyncio.Event()
    waiting = 0

    async def claim():
        nonlocal waiting
        async with db.unit_of_work() as uow:
            waiting += 1
            if waiting == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 5)
            return await uow.publications.claim(publication, NOW)

    results = await asyncio.wait_for(asyncio.gather(claim(), claim(), return_exceptions=True), 10)
    assert (
        sum(isinstance(r, PublicationError) and r.code == "publication_conflict" for r in results)
        == 1
    )
    assert sum(hasattr(r, "claim_token") for r in results) == 1


async def test_forged_attempt_cannot_confirm_and_transaction_rolls_back(chain_database):
    db = chain_database
    service = publisher(db)
    _, intent = await pending(db, service)
    post = await service.chains.finalize_intent(intent.id)
    async with db.unit_of_work() as uow:
        publication = await uow.publications.create(post.post_id, DESTINATION)
        attempt = await uow.publications.claim(publication, NOW)
    with pytest.raises(PublicationError, match="publication_conflict"):
        await service._confirm(
            publication.id,
            replace(attempt, claim_token="forged"),
            TelegramMessageRef(DESTINATION, 1),
        )
    async with db.unit_of_work() as uow:
        assert (await uow.publications.get(publication.id)).state == "sending"
        assert (
            await uow.projections.get_destination(post_id=post.post_id, chat_id=DESTINATION) is None
        )


async def test_repeated_cancellation_drains_owned_uncertainty(chain_database, monkeypatch):
    service = publisher(chain_database)
    submission, _ = await pending(chain_database, service)
    service.transport.started, service.transport.release = asyncio.Event(), asyncio.Event()
    recording, release = asyncio.Event(), asyncio.Event()
    original = service._outcome

    async def outcome(*args):
        recording.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(service, "_outcome", outcome)
    task = asyncio.create_task(service.approve_pilot(submission.id))
    await asyncio.wait_for(service.transport.started.wait(), 5)
    task.cancel()
    await asyncio.wait_for(recording.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    assert (await service.approve_pilot(submission.id)).state == "unknown"
    assert len(service.transport.sends) == 1


async def test_uncertainty_storage_outage_leaves_non_retryable_sending(chain_database, monkeypatch):
    service = publisher(chain_database)
    submission, _ = await pending(chain_database, service)
    service.transport.error = TimeoutError()

    async def unavailable(*args):
        raise RuntimeError("database unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(service, "_outcome", unavailable)
        result = await service.approve_pilot(submission.id)
    assert result.state == "sending"
    await service.recover_abandoned()
    assert (await service.approve_pilot(submission.id)).state == "unknown"
    assert len(service.transport.sends) == 1


async def test_cancellation_after_token_commit_is_markup_only_repair(chain_database, monkeypatch):
    db = chain_database
    service = publisher(db)
    submission, _ = await pending(db, service)
    editing = asyncio.Event()

    async def interrupted(*args, **kwargs):
        editing.set()
        await asyncio.Event().wait()

    with monkeypatch.context() as patch:
        patch.setattr(service.transport, "install_markup", interrupted)
        task = asyncio.create_task(service.approve_pilot(submission.id))
        await asyncio.wait_for(editing.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    result = await publisher(db, service.transport).approve_pilot(submission.id)
    assert result.state == "confirmed" and result.markup_status == "installed"
    assert len(service.transport.sends) == 1
    async with db.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(ReplyEntryTokenModel)) == 1


async def test_invalid_returned_coordinates_remain_unknown(chain_database, monkeypatch):
    service = publisher(chain_database)
    submission, _ = await pending(chain_database, service)

    async def wrong_chat(*args, **kwargs):
        return TelegramMessageRef(42, 99)

    monkeypatch.setattr(service.transport, "send", wrong_chat)
    result = await service.approve_pilot(submission.id)
    assert result.state == "unknown"
    async with chain_database.unit_of_work() as uow:
        assert (
            await uow.projections.get_destination(post_id=result.post_id, chat_id=DESTINATION)
            is None
        )
