"""D1 schema upgrade/downgrade, rollback and legacy-data preservation."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

import sqlalchemy.ext.asyncio as async_sa
from alembic.config import Config
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from alembic import command


@pytest.fixture(params=["sqlite", "postgres"])
def migrated_database(request, tmp_path, monkeypatch):
    schema = None
    if request.param == "sqlite":
        url = f"sqlite+aiosqlite:///{(tmp_path / 'discovery.sqlite3').as_posix()}"
        options = {}
    else:
        url = os.environ.get("CATS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("disposable PostgreSQL not configured")
        parsed = make_url(url)
        assert os.environ.get("CATS_TEST_POSTGRES_DISPOSABLE") == "1"
        assert parsed.host in {"127.0.0.1", "localhost"}
        assert parsed.database == parsed.username == "cats_test"
        schema = "discovery_" + uuid4().hex
        options = {"connect_args": {"server_settings": {"search_path": schema}}}

    async def execute(statement, *, unscoped=False, fetch=False):
        engine = async_sa.create_async_engine(url, **({} if unscoped else options))
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(statement))
                return result.fetchall() if fetch else None
        finally:
            await engine.dispose()

    if schema:
        asyncio.run(execute(f'CREATE SCHEMA "{schema}"', unscoped=True))
        original = async_sa.async_engine_from_config

        def configured(*args, **kwargs):
            return original(*args, **kwargs, **options)

        monkeypatch.setattr(async_sa, "async_engine_from_config", configured)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield config, execute, url, options
    finally:
        if schema:
            asyncio.run(execute(f'DROP SCHEMA "{schema}" CASCADE', unscoped=True))


def test_upgrade_downgrade_reupgrade_preserves_legacy(migrated_database):
    config, execute, _, _ = migrated_database
    command.upgrade(config, "0007_review_rejection")
    asyncio.run(
        execute(
            "INSERT INTO cat_video_submissions "
            "(id,source_provider,source_media_id,status) "
            "VALUES ('legacy','youtube','legacy','pending')"
        )
    )
    command.upgrade(config, "head")
    command.check(config)
    assert asyncio.run(execute("SELECT version_num FROM alembic_version", fetch=True)) == [
        ("0008_discovery_watchlist",)
    ]
    assert asyncio.run(execute("SELECT version FROM watchlist_control WHERE id=1", fetch=True)) == [
        (0,)
    ]
    command.downgrade(config, "0007_review_rejection")
    assert asyncio.run(
        execute("SELECT source_media_id FROM cat_video_submissions", fetch=True)
    ) == [("legacy",)]
    command.upgrade(config, "head")
    command.check(config)


def test_fresh_upgrade_and_interrupted_ddl_are_atomic(migrated_database, monkeypatch):
    config, execute, url, options = migrated_database
    command.upgrade(config, "0007_review_rejection")
    original = Operations.create_table

    def fail(operations, name, *args, **kwargs):
        result = original(operations, name, *args, **kwargs)
        if name == "watchlist_requests":
            raise RuntimeError("synthetic migration interruption")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "create_table", fail)
        with pytest.raises(RuntimeError, match="synthetic migration interruption"):
            command.upgrade(config, "head")
    assert asyncio.run(execute("SELECT version_num FROM alembic_version", fetch=True)) == [
        ("0007_review_rejection",)
    ]

    async def tables():
        engine = async_sa.create_async_engine(url, **options)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        finally:
            await engine.dispose()

    assert not {"watched_channels", "watchlist_control", "watchlist_requests"} & set(
        asyncio.run(tables())
    )
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
