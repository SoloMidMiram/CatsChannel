"""Opt-in contracts for an explicitly disposable loopback PostgreSQL database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")

from alembic.config import Config
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from cats_channel.persistence import Database, DuplicateSourceMediaError

POSTGRES_URL = os.environ.get("CATS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="disposable PostgreSQL not configured")


async def _schema_state(url):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {
                    column["name"] for column in inspect(sync).get_columns("cat_video_submissions")
                }
            )
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            return columns, revision
    finally:
        await engine.dispose()


async def _seed_legacy(url):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO cat_video_submissions (id, source_provider, source_media_id, status) "
                    "VALUES ('legacy', 'youtube', 'legacy-video', 'pending')"
                )
            )
    finally:
        await engine.dispose()


async def _transaction_contracts(url):
    database = Database(url)
    try:
        async with database.unit_of_work() as uow:
            legacy = await uow.submissions.get("legacy")
            assert legacy.source_identity_status == "unresolved"
            assert legacy.provenance == {}
            first = await uow.submissions.create(source_provider="youtube", source_media_id="first")
            second = await uow.submissions.create(
                source_provider="youtube", source_media_id="second"
            )
            now = datetime.now(UTC)
            handoff = await uow.handoffs.create(
                token_digest="a" * 64,
                actor_id=100,
                conversation_chat_id=200,
                operation="telegram_submission",
                expires_at=now + timedelta(minutes=5),
            )

        with pytest.raises(RuntimeError, match="rollback"):
            async with database.unit_of_work() as uow:
                await uow.submissions.create(
                    source_provider="youtube", source_media_id="rolled-back"
                )
                raise RuntimeError("rollback")
        async with database.unit_of_work() as uow:
            assert await uow.submissions.get_by_source_media("youtube", "rolled-back") is None

        with pytest.raises(DuplicateSourceMediaError):
            async with database.unit_of_work() as uow:
                await uow.submissions.create(source_provider="youtube", source_media_id="first")

        # Both transactions attempt the same conditional UPDATE at once. The
        # losing PostgreSQL writer must observe consumption after the winner commits.
        ready = asyncio.Event()
        waiting = 0

        async def consume(submission_id):
            nonlocal waiting
            async with database.unit_of_work() as uow:
                waiting += 1
                if waiting == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=10)
                return await uow.handoffs.consume(
                    handoff_id=handoff.id, submission_id=submission_id, consumed_at=now
                )

        results = await asyncio.wait_for(
            asyncio.gather(consume(first.id), consume(second.id)), timeout=20
        )
        assert sorted(results) == [False, True]
        async with database.unit_of_work() as uow:
            stored = await uow.handoffs.get_bound(
                token_digest="a" * 64,
                actor_id=100,
                conversation_chat_id=200,
                operation="telegram_submission",
            )
            assert stored.consumed
            assert stored.submission_id == (first.id if results[0] else second.id)
    finally:
        await database.dispose()


def test_disposable_postgres_migrations_transactions_and_handoffs(monkeypatch):
    url = make_url(POSTGRES_URL)
    assert os.environ.get("CATS_TEST_POSTGRES_DISPOSABLE") == "1"
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == url.username == "cats_test"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", POSTGRES_URL)

    command.upgrade(config, "0001_persistence_foundation")
    asyncio.run(_seed_legacy(POSTGRES_URL))
    add_column = Operations.add_column

    def fail_second_migration(operations, table_name, column, **kwargs):
        result = add_column(operations, table_name, column, **kwargs)
        if column.name == "source_channel_username":
            raise RuntimeError("migration rollback")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "add_column", fail_second_migration)
        with pytest.raises(RuntimeError, match="migration rollback"):
            command.upgrade(config, "head")
    columns, revision = asyncio.run(_schema_state(POSTGRES_URL))
    assert "source_channel_name" not in columns
    assert "source_channel_username" not in columns
    assert revision == "0001_persistence_foundation"

    command.upgrade(config, "head")
    command.check(config)
    assert asyncio.run(_schema_state(POSTGRES_URL))[1] == "0002_source_aware_submissions"
    asyncio.run(_transaction_contracts(POSTGRES_URL))
