"""CLI for one-shot discovery with an isolated synthetic fixture."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .domain import Candidate, Operator, PageResult, ProviderConfiguration, Resolution, Status
from .scanner import FetchedPage, OneShotScanner
from .service import WatchlistService

_CHANNELS = ("UC" + "a" * 22, "UC" + "b" * 22)
_OPERATOR = Operator("discovery-fixture")
_APPLICATION_ID = 0x43415453


class FixtureSource:
    def __init__(self, *, simulate_failure: bool = False):
        self._simulate_failure = simulate_failure

    def allows(self, operator, operation):
        return operator == _OPERATOR and operation == "register"

    async def resolve(self, reference: str) -> Resolution:
        return Resolution(Status.RESOLVED, reference, evidence="synthetic")

    async def page(self, entry, cursor, *, limit: int) -> FetchedPage:
        channel = _CHANNELS.index(entry.channel_id)
        start = int(cursor) if cursor is not None else 0
        if self._simulate_failure and channel == 0 and start >= 10:
            return FetchedPage(PageResult((), "failed", failure=Status.TEMPORARY_FAILURE), 0)
        stop = min(start + min(limit, 10), 20)
        now = datetime.now(UTC)
        candidates = tuple(
            Candidate(entry.channel_id, f"{channel}{index:010d}", now, "synthetic")
            for index in range(start, stop)
        )
        return FetchedPage(
            PageResult(candidates, "complete", next_cursor=str(stop) if stop < 20 else None),
            len(candidates),
        )


async def _run(args):
    from sqlalchemy import inspect, text
    from sqlalchemy.engine import URL

    from ..persistence import Database
    from ..persistence.models import Base

    path = args.fixture_db.resolve() if args.fixture_db else None
    url = URL.create("sqlite+aiosqlite", database=str(path) if path else ":memory:")
    database = Database(url.render_as_string(hide_password=False))
    try:
        async with database.engine.begin() as connection:
            application_id = await connection.scalar(text("PRAGMA application_id"))
            if application_id != _APPLICATION_ID:
                has_tables = await connection.run_sync(
                    lambda sync: bool(inspect(sync).get_table_names())
                )
                if application_id or has_tables:
                    return {"status": "error", "reason": "not_discovery_fixture_database"}
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(text(f"PRAGMA application_id = {_APPLICATION_ID}"))

        fixture = FixtureSource(simulate_failure=args.simulate_failure)
        watchlist = WatchlistService(database.unit_of_work, authorization=fixture, resolver=fixture)
        existing = {entry.reference for entry in await watchlist.list()}
        for channel in _CHANNELS:
            if channel not in existing:
                await watchlist.register(channel, operator=_OPERATOR)

        async with database.unit_of_work() as uow:
            await uow.discovery.purge_expired(now=datetime.now(UTC))

        scanner = OneShotScanner(
            database.unit_of_work,
            fixture,
            configuration=ProviderConfiguration("synthetic"),
        )
        reports = await scanner.scan(cycle=args.cycle)
        return {
            "status": "partial" if any(report.state == "partial" for report in reports) else "ok",
            "dry_run": path is None,
            "media_download": False,
            "telegram_submission": False,
            "telegram_publication": False,
            "channels": [asdict(report) for report in reports],
        }
    finally:
        await database.dispose()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cats-channel discover")
    parser.add_argument("--once", required=True, action="store_true")
    parser.add_argument("--fixture-db", type=Path, help="explicit SQLite file for synthetic state")
    parser.add_argument("--cycle", default="fixture", help="reuse this cycle ID to resume")
    parser.add_argument(
        "--simulate-failure", action="store_true", help="fail fixture channel A page 2"
    )
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(_run(args))
    except ImportError:
        report = {"status": "error", "reason": "discovery_requires_persistence_extra"}
    except Exception:  # noqa: BLE001 -- hide database paths and driver details
        report = {"status": "error", "reason": "offline_discovery_failed"}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ok" else 1
