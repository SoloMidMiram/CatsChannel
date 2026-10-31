"""Actual migration 0005 upgrade, rollback, failure atomicity and metadata parity."""

import sqlite3
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
            "0006_review_approval",
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
