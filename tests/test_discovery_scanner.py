"""One-shot recovery through the CLI and durable scanner boundary."""

import asyncio
import json
import sqlite3
import subprocess
import sys

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from test_discovery import IDS, OPERATOR, SyntheticResolver, service
from test_reply_chains import chain_database as _chain_database

from cats_channel.discovery.domain import PageResult, ProviderConfiguration, Status
from cats_channel.discovery.scanner import FetchedPage, OneShotScanner

chain_database = _chain_database


def invoke(*args):
    command = subprocess.run(
        [sys.executable, "-m", "cats_channel", "discover", "--once", *map(str, args)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return command.returncode, json.loads(command.stdout)


def test_cli_dry_run_and_durable_restart(tmp_path):
    code, report = invoke()
    assert code == 0 and report["dry_run"]
    assert report["media_download"] is report["telegram_submission"] is False
    assert report["telegram_publication"] is False
    assert sorted(channel["items"] for channel in report["channels"]) == [20, 20]

    path = tmp_path / "fixture.sqlite3"
    code, first = invoke("--fixture-db", path, "--simulate-failure")
    assert code == 1 and not first["dry_run"]
    assert sorted((channel["state"], channel["items"]) for channel in first["channels"]) == [
        ("completed", 20),
        ("partial", 10),
    ]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM discovery_candidates").fetchone() == (30,)
        assert db.execute(
            "SELECT count(*) FROM discovery_checkpoints WHERE coverage_through IS NOT NULL"
        ).fetchone() == (1,)

    code, final = invoke("--fixture-db", path)
    assert code == 0
    assert sorted(channel["items"] for channel in final["channels"]) == [0, 10]
    assert sum(channel["request_attempts"] for channel in final["channels"]) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM discovery_candidates").fetchone() == (40,)
        assert db.execute("SELECT count(*) FROM discovery_observations").fetchone() == (40,)


def test_cli_rejects_other_sqlite_databases(tmp_path):
    path = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE original (id INTEGER)")
    assert invoke("--fixture-db", path) == (
        1,
        {"status": "error", "reason": "not_discovery_fixture_database"},
    )


class Pages:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.cursors = []

    async def page(self, entry, cursor, *, limit):
        self.cursors.append(cursor)
        page = next(self.pages)
        if isinstance(page, BaseException):
            raise page
        return FetchedPage(page, 0)


async def setup(db):
    watchlist = service(db, SyntheticResolver())
    entry = (await watchlist.register(IDS[0], operator=OPERATOR)).entry
    return watchlist, entry


def scanner(db, provider, *, requests=30, pages=2, adapter="synthetic"):
    return OneShotScanner(
        db.unit_of_work,
        provider,
        page_budget=pages,
        configuration=ProviderConfiguration(adapter, request_budget=requests),
    )


async def test_budget_configuration_and_disabled_retired_channels(chain_database):
    db = chain_database
    watchlist, first = await setup(db)
    second = (await watchlist.register(IDS[1], operator=OPERATOR)).entry
    third = (await watchlist.register(IDS[2], operator=OPERATOR)).entry
    await watchlist.set_enabled(second.id, False, operator=OPERATOR)
    await watchlist.retire(third.id, operator=OPERATOR)
    provider = Pages(PageResult((), "complete", next_cursor="next"))
    [report] = await scanner(db, provider, requests=1).scan(cycle="budget")
    assert report.watchlist_id == first.id and report.reason == "budget_exhausted"
    assert report.request_attempts == report.page_attempts == 1
    assert provider.cursors == [None]
    [changed] = await scanner(db, Pages(), requests=2).scan(cycle="budget")
    assert changed.reason == "scan_scope_changed"


@pytest.mark.parametrize("expired", [False, True])
async def test_cursor_restart_is_bounded_and_preserves_run_start(chain_database, expired):
    db = chain_database
    _, entry = await setup(db)
    failure = (
        PageResult((), "failed", failure=Status.CURSOR_EXPIRED)
        if expired
        else PageResult((), "complete", next_cursor="next")
    )
    provider = Pages(
        PageResult((), "complete", next_cursor="next"), failure, PageResult((), "complete")
    )
    [report] = await scanner(db, provider, pages=3).scan(cycle="restart")
    assert report.state == "completed"
    assert provider.cursors == [None, "next", None]
    assert report.request_attempts == 3
    async with db.unit_of_work() as uow:
        coverage, last_success = await uow.discovery.coverage(entry.id, "youtube")
    assert coverage < last_success


@pytest.mark.parametrize("committed", [False, True])
async def test_database_failure_reconciles_on_next_invocation(
    chain_database, committed, monkeypatch
):
    db = chain_database
    await setup(db)
    first = scanner(db, Pages(PageResult((), "complete", next_cursor="next")))
    record = first._record

    async def fail(*args):
        if committed:
            await record(*args)
        raise OSError("fixture driver failure")

    monkeypatch.setattr(first, "_record", fail)
    with pytest.raises(OSError):
        await first.scan(cycle="failure")
    provider = Pages(PageResult((), "complete"))
    [report] = await scanner(db, provider).scan(cycle="failure")
    assert report.state == "completed"
    assert provider.cursors == ["next" if committed else None]


async def test_provider_cancellation_propagates(chain_database):
    db = chain_database
    await setup(db)
    provider = Pages(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await scanner(db, provider).scan(cycle="cancel")
    provider = Pages(PageResult((), "complete"))
    [report] = await scanner(db, provider).scan(cycle="cancel")
    assert report.state == "completed" and provider.cursors == [None]
