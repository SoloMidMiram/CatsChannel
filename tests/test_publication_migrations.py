"""Actual migration 0005 upgrade, rollback, failure atomicity and metadata parity."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from alembic.config import Config
from alembic.operations import Operations

from alembic import command


def configuration(tmp_path, monkeypatch):
    path = tmp_path / "publication.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    return config, path


def test_upgrade_downgrade_and_schema_parity(tmp_path, monkeypatch):
    config, path = configuration(tmp_path, monkeypatch)
    command.upgrade(config, "head")
    command.check(config)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0008_discovery_watchlist",
        )
        assert "uq_destination_post_chat" in {
            r[1] for r in connection.execute("PRAGMA index_list(telegram_message_refs)")
        }
    command.downgrade(config, "0004_bot_submission_intake")
    with sqlite3.connect(path) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master")}
        assert not tables & {"publications", "publication_attempts"}
        assert "uq_destination_post_chat" not in tables
    command.upgrade(config, "head")
    command.check(config)


def test_rejection_upgrade_retains_audit_and_blocks_lossy_downgrade(tmp_path, monkeypatch):
    from cats_channel.persistence import Database

    config, path = configuration(tmp_path, monkeypatch)
    command.upgrade(config, "head")

    async def reject():
        database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
        try:
            async with database.unit_of_work() as uow:
                submission = await uow.submissions.create(
                    source_provider="telegram",
                    source_media_id="migration-fixture",
                    status="validated",
                )
                item = await uow.reviews.create(submission.id, -100456, -100789)
                assert await uow.reviews.claim_delivery(item)
                item = await uow.reviews.finish_delivery(item, "confirmed", message_id=99)
                assert await uow.reviews.reject(item, 42, datetime.now(UTC), "unsuitable")
        finally:
            await database.dispose()

    asyncio.run(reject())
    with pytest.raises(RuntimeError, match="audited rejections"):
        command.downgrade(config, "0006_review_approval")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT decision_state, decision_action, rejection_reason FROM review_items"
        ).fetchone() == ("rejected", "reject", "unsuitable")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0008_discovery_watchlist",
        )


def test_rejection_ddl_failure_rolls_back(tmp_path, monkeypatch):
    config, path = configuration(tmp_path, monkeypatch)
    command.upgrade(config, "0006_review_approval")
    from alembic.operations import BatchOperations

    add_column = BatchOperations.add_column

    def fail(batch, column, *args, **kwargs):
        add_column(batch, column, *args, **kwargs)
        if column.name == "rejection_reason":
            raise RuntimeError("rejection migration interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(BatchOperations, "add_column", fail)
        with pytest.raises(RuntimeError, match="migration interrupted"):
            command.upgrade(config, "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0006_review_approval",
        )
        assert "decision_action" not in {
            row[1] for row in connection.execute("PRAGMA table_info(review_items)")
        }
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_publication_ddl_rollback(tmp_path, monkeypatch, failure):
    config, path = configuration(tmp_path, monkeypatch)
    command.upgrade(config, "0004_bot_submission_intake")
    create_table = Operations.create_table

    def fail(operations, name, *args, **kwargs):
        result = create_table(operations, name, *args, **kwargs)
        if name == "publication_attempts":
            raise failure("publication migration interrupted")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "create_table", fail)
        with pytest.raises(failure, match="publication migration interrupted"):
            command.upgrade(config, "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0004_bot_submission_intake",
        )
        assert not {"publications", "publication_attempts"} & {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master")
        }
    command.upgrade(config, "head")
    command.check(config)


def test_duplicate_legacy_projections_fail_migration_without_deleting_data(tmp_path, monkeypatch):
    config, path = configuration(tmp_path, monkeypatch)
    command.upgrade(config, "0004_bot_submission_intake")
    # Isolated legacy fixture. SQLite connection intentionally has FK checks off.
    with sqlite3.connect(path) as connection:
        for n in (1, 2):
            connection.execute(
                "INSERT INTO telegram_message_refs(id,purpose,chat_id,message_id,post_id) VALUES (?, 'destination', -100123, ?, 'legacy-post')",
                (str(n), n),
            )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        command.upgrade(config, "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM telegram_message_refs").fetchone() == (2,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0004_bot_submission_intake",
        )
