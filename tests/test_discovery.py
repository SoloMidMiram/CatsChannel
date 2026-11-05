"""Offline watchlist acceptance, shared across SQLite and disposable PostgreSQL."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from sqlalchemy import func, select
from test_reply_chains import chain_database as _chain_database

from cats_channel.discovery.domain import (
    Candidate,
    Operator,
    PageResult,
    Resolution,
    ScanPolicy,
    Status,
    WatchlistError,
    normalize,
)
from cats_channel.discovery.service import WatchlistService
from cats_channel.persistence import Database
from cats_channel.persistence.discovery_repositories import SqlAlchemyWatchlistRepository
from cats_channel.persistence.models import CatVideoSubmissionModel, WatchlistEventModel

chain_database = _chain_database
IDS = tuple("UC" + str(i) * 22 for i in range(3))
OPERATOR = Operator("local-owner")


@pytest.fixture(autouse=True)
def no_acquisition_or_telegram(monkeypatch):
    from aiogram import Bot

    from cats_channel.services.media_service import MediaService

    acquire = AsyncMock(side_effect=AssertionError("D1 attempted acquisition"))
    send = AsyncMock(side_effect=AssertionError("D1 attempted Telegram send"))
    monkeypatch.setattr(MediaService, "acquire_async", acquire)
    monkeypatch.setattr(Bot, "send_video", send)
    yield
    acquire.assert_not_called()
    send.assert_not_called()


class Authorization:
    def allows(self, operator, operation):
        return operator == OPERATOR


class SyntheticResolver:
    def __init__(self):
        self.values = {}
        self.calls = []
        for index, channel_id in enumerate(IDS):
            value = Resolution(
                Status.RESOLVED, channel_id, f"@cat{index}", f"Synthetic cat {index}", "synthetic"
            )
            self.values[channel_id] = value
            self.values[f"@cat{index}"] = value

    async def resolve(self, reference):
        self.calls.append(reference)
        return self.values.get(reference, Resolution(Status.UNAVAILABLE))


def service(db, resolver=None, capacity=100):
    return WatchlistService(
        db.unit_of_work, authorization=Authorization(), resolver=resolver, capacity=capacity
    )


async def test_three_channels_alias_rename_disable_policy_and_retire(chain_database):
    resolver = SyntheticResolver()
    app = service(chain_database, resolver)
    a = (await app.register(IDS[0], operator=OPERATOR)).entry
    b = (await app.register("@cat1", operator=OPERATOR)).entry
    c = (
        await app.register(f"https://www.youtube.com/channel/{IDS[2]}/shorts", operator=OPERATOR)
    ).entry
    alias = await app.register("https://youtube.com/@cat0/shorts", operator=OPERATOR)
    assert alias.entry.id == a.id and alias.outcome == "already_known"
    resolver.values[IDS[0]] = replace(resolver.values[IDS[0]], handle="@newcat")
    resolver.values["@newcat"] = resolver.values[IDS[0]]
    renamed = await app.register("@newcat", operator=OPERATOR)
    assert renamed.entry.id == a.id and renamed.outcome == "renamed"
    await app.set_enabled(b.id, False, operator=OPERATOR)
    await app.set_scan_policy(a.id, ScanPolicy(12, 7), operator=OPERATOR)
    await app.retire(c.id, operator=OPERATOR)
    scanner = await app.list(scanner=True)
    assert len(scanner) == 1 and scanner[0].id == a.id
    assert scanner[0].policy == ScanPolicy(12, 7)
    assert len(await app.list()) == 3
    assert (await app.inspect(c.id)).retired
    with pytest.raises(WatchlistError, match="retired"):
        await app.set_enabled(c.id, True, operator=OPERATOR)
    assert scanner[0].canonical_url == f"https://www.youtube.com/channel/{IDS[0]}"
    async with chain_database.unit_of_work() as uow:
        assert (
            await uow._session.scalar(select(func.count()).select_from(CatVideoSubmissionModel))
            == 0
        )
        events = list(await uow._session.scalars(select(WatchlistEventModel)))
        assert events and all(event.operator == OPERATOR.name for event in events)


@pytest.mark.parametrize(
    "value",
    [
        "cat name",
        "UCwrong",
        "http://youtube.com/@cat0",
        "https://youtube.com.evil/@cat0",
        "https://youtube.com:443/@cat0",
        "https://owner@youtube.com/@cat0",
        "https://youtube.com/@cat0?x=1",
        "https://youtube.com/@cat0#x",
        "https://youtube.com/@cat0%2Fshorts",
        "https://youtube.com/watch?v=123",
        "file:///etc/passwd",
        "@a",
        "https://youtube.com/@cat0/../@cat1",
        "https://youtube.com/user/name",
        "https://youtube.com/channel/@cat0",
        "https://youtube.com/UC" + "0" * 22,
    ],
)
def test_reject_malicious_and_ambiguous_inputs(value):
    with pytest.raises(ValueError, match="invalid_input"):
        normalize(value)


async def test_authorization_precedes_provider_and_storage(chain_database):
    resolver = AsyncMock()
    app = service(chain_database, resolver)
    for operator in (None, Operator("stranger")):
        for action in (
            app.register("@cat0", operator=operator),
            app.refresh_resolution("missing", operator=operator),
            app.set_enabled("missing", True, operator=operator),
            app.set_scan_policy("missing", ScanPolicy(), operator=operator),
            app.retire("missing", operator=operator),
        ):
            with pytest.raises(WatchlistError, match="unauthorized"):
                await action
    resolver.resolve.assert_not_called()
    assert await app.list() == ()


@pytest.mark.parametrize(
    "status",
    [
        Status.UNAVAILABLE,
        Status.AMBIGUOUS,
        Status.RATE_LIMITED,
        Status.TEMPORARY_FAILURE,
        Status.INVALID_INPUT,
    ],
)
async def test_failure_outcomes_are_durable_and_never_scanned(chain_database, status):
    resolver = SyntheticResolver()
    resolver.values["@cat0"] = Resolution(status, retry_after_seconds=10)
    app = service(chain_database, resolver)
    entry = (await app.register("@cat0", operator=OPERATOR)).entry
    assert entry.channel_id is None and entry.status == status
    assert (await app.inspect(entry.id)).retry_after_seconds == 10
    assert await app.list(scanner=True) == ()


async def test_missing_resolver_then_request_slot_transfer(chain_database):
    app = service(chain_database, capacity=1)
    pending = (await app.register("@cat0", operator=OPERATOR)).entry
    assert pending.evidence == "resolver_not_configured"
    await app.set_scan_policy(pending.id, ScanPolicy(5, 6), operator=OPERATOR)
    app.resolver = SyntheticResolver()
    resolved = await app.refresh_resolution(pending.id, operator=OPERATOR)
    assert resolved.channel_id == IDS[0]
    assert resolved.policy == ScanPolicy(5, 6)
    assert not resolved.enabled
    assert (await app.inspect(pending.id)).id == resolved.id
    assert len(await app.list()) == 1
    app.resolver.values["@cat0"] = app.resolver.values[IDS[1]]
    # A resolved request is not a permanent alias binding, even after later reassignment.
    app.capacity = 2
    reassigned = (await app.register("@cat0", operator=OPERATOR)).entry
    assert reassigned.channel_id == IDS[1]
    assert (await app.inspect(pending.id)).channel_id == IDS[0]


async def test_handle_reassignment_does_not_change_old_identity(chain_database):
    resolver = SyntheticResolver()
    app = service(chain_database, resolver)
    original = (await app.register("@cat0", operator=OPERATOR)).entry
    resolver.values["@cat0"] = resolver.values[IDS[1]]
    reassigned = (await app.register("@cat0", operator=OPERATOR)).entry
    assert reassigned.channel_id == IDS[1] and reassigned.id != original.id
    assert (await app.inspect(original.id)).channel_id == IDS[0]


async def test_concurrent_duplicates_and_capacity(chain_database):
    app = service(chain_database, SyntheticResolver(), capacity=1)
    duplicate = await asyncio.gather(*(app.register("@cat0", operator=OPERATOR) for _ in range(4)))
    assert len({result.entry.id for result in duplicate}) == 1
    with pytest.raises(WatchlistError, match="capacity_exceeded"):
        await app.register("@cat1", operator=OPERATOR)
    await app.retire(duplicate[0].entry.id, operator=OPERATOR)
    contenders = await asyncio.gather(
        *(app.register(f"@cat{i}", operator=OPERATOR) for i in (1, 2)), return_exceptions=True
    )
    assert sum(not isinstance(result, Exception) for result in contenders) == 1
    assert sum(isinstance(result, WatchlistError) for result in contenders) == 1


async def test_rollback_and_cancel_leave_no_partial_identity(chain_database, monkeypatch):
    app = service(chain_database, SyntheticResolver())
    original = SqlAlchemyWatchlistRepository.event

    async def fail(*args):
        raise RuntimeError("synthetic rollback")

    monkeypatch.setattr(SqlAlchemyWatchlistRepository, "event", fail)
    with pytest.raises(RuntimeError, match="synthetic rollback"):
        await app.register("@cat0", operator=OPERATOR)
    assert await app.list() == ()
    monkeypatch.setattr(SqlAlchemyWatchlistRepository, "event", original)
    app.resolver = AsyncMock()
    app.resolver.resolve.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await app.register("@cat0", operator=OPERATOR)
    assert await app.list() == ()


async def test_stale_resolution_cannot_undo_operator_changes(chain_database):
    app = service(chain_database, SyntheticResolver())
    entry = (await app.register("@cat0", operator=OPERATOR)).entry
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(_):
        started.set()
        await release.wait()
        return Resolution(Status.RESOLVED, IDS[0], "@renamed", evidence="synthetic")

    app.resolver = AsyncMock()
    app.resolver.resolve.side_effect = delayed
    task = asyncio.create_task(app.refresh_resolution(entry.id, operator=OPERATOR))
    await started.wait()
    await app.retire(entry.id, operator=OPERATOR)
    release.set()
    with pytest.raises(WatchlistError, match="stale_resolution"):
        await task
    assert (await app.inspect(entry.id)).retired


async def test_unavailable_then_recovery_and_sanitized_provider_exception(chain_database):
    resolver = SyntheticResolver()
    app = service(chain_database, resolver)
    entry = (await app.register(IDS[0], operator=OPERATOR)).entry
    resolver.values[IDS[0]] = Resolution(Status.UNAVAILABLE)
    missing = await app.refresh_resolution(entry.id, operator=OPERATOR)
    assert missing.handle is None and missing.last_resolved_at == entry.last_resolved_at
    assert not await app.list(scanner=True)
    app.resolver = AsyncMock()
    app.resolver.resolve.side_effect = RuntimeError("SECRET_PROVIDER_PAYLOAD")
    failure = await app.refresh_resolution(entry.id, operator=OPERATOR)
    assert failure.status == Status.TEMPORARY_FAILURE
    assert "SECRET" not in repr(failure)


async def test_restart_and_keyset_pagination(chain_database):
    app = service(chain_database, SyntheticResolver())
    for channel_id in IDS:
        await app.register(channel_id, operator=OPERATOR)
    url = chain_database.engine.url.render_as_string(hide_password=False)
    # Preserve the schema-setting fixture for PostgreSQL; engine.dispose recreates connections.
    await chain_database.dispose()
    restarted = service(chain_database, SyntheticResolver())
    first = await restarted.list(limit=2)
    second = await restarted.list(after=first[-1].id, limit=2)
    assert len(first) == 2 and len(second) == 1
    assert len({entry.channel_id for entry in first + second}) == 3
    if chain_database.engine.dialect.name == "sqlite":
        fresh = Database(url)
        try:
            assert len(await service(fresh).list()) == 3
        finally:
            await fresh.dispose()


async def test_cancellation_during_transaction_rolls_back(chain_database, monkeypatch):
    app = service(chain_database, SyntheticResolver())

    async def cancel(*_):
        raise asyncio.CancelledError

    monkeypatch.setattr(SqlAlchemyWatchlistRepository, "event", cancel)
    with pytest.raises(asyncio.CancelledError):
        await app.register("@cat0", operator=OPERATOR)
    assert await app.list() == ()


async def test_bounded_history_retains_operator_snapshots(chain_database):
    app = service(chain_database, SyntheticResolver())
    entry = (await app.register("@cat0", operator=OPERATOR)).entry
    for index in range(102):
        await app.set_enabled(entry.id, index % 2 == 0, operator=OPERATOR)
    events = await app.history(entry.id)
    assert len(events) == 100
    assert events[0].version == 103
    assert all(event.operator == OPERATOR.name and event.handle == "@cat0" for event in events)


async def test_delayed_alias_cannot_overwrite_newer_metadata(chain_database):
    resolver = SyntheticResolver()
    app = service(chain_database, resolver)
    entry = (await app.register(IDS[0], operator=OPERATOR)).entry
    started, release = asyncio.Event(), asyncio.Event()

    async def resolve(reference):
        if reference == "@oldalias":
            started.set()
            await release.wait()
            return Resolution(Status.RESOLVED, IDS[0], "@oldalias", evidence="synthetic")
        return Resolution(Status.RESOLVED, IDS[0], "@newalias", evidence="synthetic")

    app.resolver = AsyncMock()
    app.resolver.resolve.side_effect = resolve
    task = asyncio.create_task(app.register("@oldalias", operator=OPERATOR))
    await started.wait()
    await app.refresh_resolution(entry.id, operator=OPERATOR)
    release.set()
    assert (await task).entry.handle == "@newalias"
    assert (await app.inspect(entry.id)).handle == "@newalias"


def test_future_candidate_does_not_infer_shorts_from_duration():
    from datetime import UTC, datetime

    candidate = Candidate(
        IDS[0], "abc12345678", datetime.now(UTC), "synthetic", duration_seconds=10
    )
    assert candidate.classification == "unknown"
    assert not PageResult((candidate,), "partial", "next").checkpoint_may_advance
    assert not PageResult((), "failed", failure=Status.RATE_LIMITED).checkpoint_may_advance
    assert PageResult((candidate,), "complete").checkpoint_may_advance
