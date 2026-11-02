"""Disposable offline restore preserves uncertain sends and terminal rejection."""

import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from sqlalchemy import text
from test_publication import Transport, pending, publisher
from test_reply_chains import chain_database as _chain_database

from cats_channel.persistence import Database, TelegramMessageRef
from cats_channel.review.service import ReviewService

chain_database = _chain_database


def postgres_tool(arguments, url):
    environment = os.environ.copy()
    environment.update(
        PGHOST=url.host,
        PGPORT=str(url.port or 5432),
        PGUSER=url.username,
        PGPASSWORD=url.password or "",
        PGDATABASE=url.database,
    )
    # Password never appears in argv, diagnostics or fixture output.
    result = subprocess.run(
        arguments, env=environment, capture_output=True, timeout=45, check=False
    )
    assert result.returncode == 0, "Disposable PostgreSQL backup/restore tool failed"


async def test_disposable_restore_preserves_rejected_and_unknown_without_resend(
    chain_database, tmp_path
):
    database = chain_database
    backend = database.engine.dialect.name
    if backend == "postgresql":
        assert all(shutil.which(tool) for tool in ("pg_dump", "pg_restore")), (
            "Configured PostgreSQL qualification requires pg_dump and pg_restore"
        )
    delivery = Transport()
    original = publisher(database, delivery)
    confirmed, _ = await pending(database, original, source="restore-confirmed")
    confirmed_publication = await original.approve_pilot(confirmed.id)
    assert confirmed_publication.state == "confirmed"
    uncertain, _ = await pending(database, original, source="restore-unknown")
    delivery.error = TimeoutError("synthetic ambiguous send")
    publication = await original.approve_pilot(uncertain.id)
    assert publication.state == "unknown" and len(delivery.sends) == 2
    rejected, _ = await pending(database, original, source="restore-rejected")
    preview = AsyncMock()
    preview.send_review.return_value = TelegramMessageRef(-100456, 99)
    review = ReviewService(
        database.unit_of_work,
        transport=preview,
        publication_service=original,
        review_chat_id=-100456,
        destination_chat_id=original.destination,
        admin_user_id=42,
    )
    item = await review.enqueue(rejected.id)
    decided = await review.reject(item.id, 1, actor_id=42, chat_id=-100456, message_id=99)
    assert decided.decision_state == "rejected"
    async with database.engine.connect() as connection:
        schema = (
            await connection.scalar(text("SELECT current_schema()"))
            if backend == "postgresql"
            else None
        )
    # No writer/poller exists; all fixture service transactions have committed.
    await database.dispose()
    restored = database
    archive = tmp_path / ("backup.dump" if backend == "postgresql" else "backup.sqlite3")
    if backend == "sqlite":
        source = Path(database.engine.url.database).resolve()
        assert source.is_relative_to(tmp_path.parent.resolve())
        with sqlite3.connect(source) as src, sqlite3.connect(archive) as dest:
            src.backup(dest)
        with sqlite3.connect(archive) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        restored = Database(f"sqlite+aiosqlite:///{archive.as_posix()}")
    else:
        url = database.engine.url
        assert os.environ.get("CATS_TEST_POSTGRES_DISPOSABLE") == "1"
        assert (
            url.host in {"127.0.0.1", "localhost"} and url.database == url.username == "cats_test"
        )
        assert re.fullmatch(r"reply_[0-9a-f]{32}", schema)
        postgres_tool(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--schema",
                schema,
                "--file",
                str(archive),
            ],
            url,
        )
        async with database.engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await database.dispose()
        try:
            postgres_tool(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    url.database,
                    str(archive),
                ],
                url,
            )
        finally:
            # Ensure the disposable fixture can clean up even if restore fails.
            async with database.engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await database.dispose()
    try:
        no_send = Transport()
        recovered = publisher(restored, no_send)
        await recovered.recover_abandoned()
        restarted_review = ReviewService(
            restored.unit_of_work,
            transport=preview,
            publication_service=recovered,
            review_chat_id=-100456,
            destination_chat_id=recovered.destination,
            admin_user_id=42,
        )
        await restarted_review.recover_abandoned()
        stored = await restarted_review.get(item.id)
        assert stored.decision_state == "rejected" and stored.decision_action == "reject"
        assert stored.rejection_reason == "unsuitable" and stored.reviewer_id == 42
        assert stored.reviewed_at == decided.reviewed_at and stored.version == decided.version
        async with restored.unit_of_work() as uow:
            pub = await uow.publications.get(publication.id)
            assert (
                pub.state == "unknown" and pub.current_attempt_id == publication.current_attempt_id
            )
            assert (await uow.submissions.get(rejected.id)).status == "rejected"
            assert await uow.threads.get_post_for_submission(rejected.id) is None
            stored_confirmation = await uow.publications.get(confirmed_publication.id)
            assert stored_confirmation.state == "confirmed"
            projection = await uow.projections.get_destination(
                post_id=stored_confirmation.post_id, chat_id=original.destination
            )
            assert projection.reference == TelegramMessageRef(original.destination, 1)
        assert (await recovered.approve_pilot(confirmed.id)).state == "confirmed"
        duplicate = await recovered.approve_pilot(uncertain.id)
        assert duplicate.state == "unknown" and no_send.sends == []
        assert (
            await restarted_review.approve(item.id, 1, actor_id=42, chat_id=-100456, message_id=99)
        ).decision_state == "rejected"
        assert no_send.sends == []
    finally:
        if restored is not database:
            await restored.dispose()
