"""Discovery ledger durability and fencing on SQLite and disposable PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from test_discovery import IDS, OPERATOR, SyntheticResolver, service
from test_reply_chains import chain_database as _chain_database

from cats_channel.discovery.domain import Candidate, PageResult, Status, WatchlistError

chain_database = _chain_database


def candidate(channel, video="abcdefghijk", *, method="synthetic"):
    return Candidate(channel, video, datetime.now(UTC), method, title="Fixture")


async def claim(db, channel, *, cycle="fixture"):
    async with db.unit_of_work() as uow:
        return await uow.discovery.claim(
            channel, provider="youtube", fingerprint="a" * 64, cycle=cycle
        )


async def write(db, lease, page, *, coverage=None):
    async with db.unit_of_work() as uow:
        return await uow.discovery.record_page(
            lease,
            page,
            items_examined=len(page.candidates),
            requests=1,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            coverage_through=coverage,
        )


async def list_candidates(db, channel, *, now=None):
    async with db.unit_of_work() as uow:
        return await uow.discovery.list_candidates(channel, now=now or datetime.now(UTC))


async def test_recovery_and_stale_writer(chain_database):
    db = chain_database
    watchlist = service(db, SyntheticResolver())
    a = (await watchlist.register(IDS[0], operator=OPERATOR)).entry
    b = (await watchlist.register(IDS[1], operator=OPERATOR)).entry
    one = candidate(IDS[0])
    two = candidate(IDS[1], "bcdefghijkl")
    first = await claim(db, a.id)
    first = await write(db, first, PageResult((one,), "complete", next_cursor="page-2"))
    first = await write(db, first, PageResult((), "failed", failure=Status.TEMPORARY_FAILURE))
    second = await claim(db, b.id)
    await write(db, second, PageResult((two,), "complete"), coverage=datetime.now(UTC))
    resumed = await claim(db, a.id)
    assert resumed.cursor == "page-2" and resumed.state == "backlog"
    assert (await claim(db, b.id)).state == "completed"
    with pytest.raises(WatchlistError, match="stale_scan_owner"):
        await write(db, first, PageResult((), "failed"))
    final = await write(db, resumed, PageResult((one,), "complete"), coverage=datetime.now(UTC))
    assert final.state == "completed"
    assert len(await list_candidates(db, a.id)) == len(await list_candidates(db, b.id)) == 1


async def test_cursor_restart_and_retention(chain_database):
    db = chain_database
    watchlist = service(db, SyntheticResolver())
    a = (await watchlist.register(IDS[0], operator=OPERATOR)).entry
    first = await claim(db, a.id)
    one = candidate(IDS[0])
    first = await write(db, first, PageResult((one,), "complete", next_cursor="page-2"))
    with pytest.raises(WatchlistError, match="scan_cursor_restart_required"):
        await write(db, first, PageResult((), "complete", next_cursor="page-2"))
    async with db.unit_of_work() as uow:
        restarted = await uow.discovery.restart(first)
    assert restarted.cursor is None
    assert len(await list_candidates(db, a.id)) == 1
    future = datetime.now(UTC) + timedelta(days=8)
    assert not await list_candidates(db, a.id, now=future)
    async with db.unit_of_work() as uow:
        await uow.discovery.purge_expired(now=future)
    assert not await list_candidates(db, a.id)
    assert (await claim(db, a.id)).run_id != restarted.run_id


async def test_invalid_page_rolls_back_and_watchlist_edits_fence(chain_database):
    db = chain_database
    watchlist = service(db, SyntheticResolver())
    a = (await watchlist.register(IDS[0], operator=OPERATOR)).entry
    lease = await claim(db, a.id)
    correct = candidate(IDS[0])
    wrong = candidate(IDS[1], "bcdefghijkl")
    with pytest.raises(WatchlistError, match="candidate_source_mismatch"):
        await write(db, lease, PageResult((correct, wrong), "complete", next_cursor="page-2"))
    assert not await list_candidates(db, a.id)
    with pytest.raises(WatchlistError, match="data_category_unapproved"):
        await write(db, lease, PageResult((candidate(IDS[0], method="youtube_uush"),), "partial"))
    assert (await claim(db, a.id)).cursor is None
    lease = await claim(db, a.id)
    await watchlist.set_enabled(a.id, False, operator=OPERATOR)
    with pytest.raises(WatchlistError, match="stale_scan_owner"):
        await write(db, lease, PageResult((), "failed"))
    with pytest.raises(WatchlistError, match="channel_not_scannable"):
        await claim(db, a.id)


async def test_concurrent_reclaim_and_independent_full_coverage(chain_database):
    db = chain_database
    app = service(db, SyntheticResolver())
    channel = (await app.register(IDS[0], operator=OPERATOR)).entry
    owners = await asyncio.gather(claim(db, channel.id), claim(db, channel.id))
    stale, current = sorted(owners, key=lambda owner: owner.version)
    item = candidate(IDS[0])
    page = PageResult((item,), "complete", next_cursor="next")
    with pytest.raises(WatchlistError, match="stale_scan_owner"):
        await write(db, stale, page)
    current = await write(db, current, page)
    async with db.unit_of_work() as uow:
        assert await uow.discovery.coverage(channel.id, "youtube") == (None, None)

    cutoff = datetime.now(UTC)
    await write(db, current, PageResult((item,), "complete"), coverage=cutoff)
    other_cycle = await claim(db, channel.id, cycle="other")
    await write(db, other_cycle, PageResult((), "failed", failure=Status.TEMPORARY_FAILURE))
    async with db.unit_of_work() as uow:
        coverage, last_success = await uow.discovery.coverage(channel.id, "youtube")
    assert coverage == cutoff and last_success >= cutoff
    assert len(await list_candidates(db, channel.id)) == 1


@pytest.mark.parametrize("offset", [0, 2])
async def test_current_metadata_survives_nulls_and_offsets(chain_database, offset):
    from dataclasses import replace
    from datetime import timezone

    from sqlalchemy import select

    from cats_channel.persistence.models import discovery_observations

    db = chain_database
    entry = (await service(db, SyntheticResolver()).register(IDS[0], operator=OPERATOR)).entry
    instant = datetime.now(UTC) - timedelta(minutes=3)
    zone = timezone(timedelta(hours=offset))
    first = replace(candidate(IDS[0]), observed_at=instant.astimezone(zone), published_at=instant)
    newer = replace(
        first, observed_at=instant + timedelta(minutes=1), title=None, published_at=None
    )
    lease = await claim(db, entry.id)
    lease = await write(db, lease, PageResult((first,), "complete", next_cursor="next"))
    expiry = datetime.now(UTC) + timedelta(minutes=20)
    async with db.unit_of_work() as uow:
        await uow.discovery.record_page(
            lease,
            PageResult((newer,), "complete"),
            items_examined=1,
            requests=1,
            expires_at=expiry.astimezone(zone),
            coverage_through=instant.astimezone(zone),
        )
    [row] = await list_candidates(db, entry.id)
    assert row["last_seen"].replace(tzinfo=UTC) == newer.observed_at
    assert row["current"]["title"] == first.title
    assert row["current"]["published_at"] == instant.isoformat()
    assert await list_candidates(db, entry.id, now=(expiry - timedelta(seconds=1)).astimezone(zone))
    assert not await list_candidates(db, entry.id, now=expiry)
    async with db.unit_of_work() as uow:
        coverage, _ = await uow.discovery.coverage(entry.id, "youtube")
    assert coverage == instant
    async with db.engine.connect() as connection:
        history = (
            (
                await connection.execute(
                    select(discovery_observations.c.data).order_by(
                        discovery_observations.c.observed_at
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(history) == 2
    assert history[-1]["title"] is None and history[-1]["published_at"] is None
