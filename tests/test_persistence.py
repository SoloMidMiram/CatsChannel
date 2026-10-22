from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from alembic.config import Config
from alembic.operations import BatchOperations, Operations
from sqlalchemy.exc import InvalidRequestError

from alembic import command
from cats_channel.config import Settings
from cats_channel.persistence import (
    ConcurrentThreadUpdateError,
    CrossThreadParentError,
    Database,
    DuplicateSourceMediaError,
    DuplicateTelegramMessageError,
    SourceIdentity,
    TelegramMessageRef,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


@pytest.fixture
async def database(tmp_path):
    value = Database(sqlite_url(tmp_path / "contracts.sqlite3"))
    await value.create_schema_for_tests()
    try:
        yield value
    finally:
        await value.dispose()


def test_database_configuration_accepts_async_drivers_and_hides_credentials():
    sqlite = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    postgres = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://cat:private@database/cats",
    )

    assert sqlite.database_url.get_secret_value().startswith("sqlite+aiosqlite:")
    assert postgres.database_url.get_secret_value().startswith("postgresql+asyncpg:")
    assert "private" not in repr(postgres)


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///sync.sqlite3",
        "postgresql://cat:secret@database/cats",
        "mysql+aiomysql://database/cats",
        "sqlite+aiosqlite://",
        "postgresql+asyncpg://database/",
    ],
)
def test_database_configuration_rejects_sync_or_unsupported_drivers(database_url):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(_env_file=None, database_url=database_url)


async def test_unit_of_work_commits_and_rolls_back(database):
    async with database.unit_of_work() as uow:
        committed = await uow.submissions.create(
            source_provider="youtube", source_media_id="committed"
        )

    with pytest.raises(RuntimeError, match="abort"):
        async with database.unit_of_work() as uow:
            await uow.submissions.create(source_provider="youtube", source_media_id="rolled-back")
            raise RuntimeError("abort")

    async with database.unit_of_work() as uow:
        assert (
            await uow.submissions.get_by_source_media("youtube", "committed")
        ).id == committed.id
        assert await uow.submissions.get_by_source_media("youtube", "rolled-back") is None


async def test_source_display_change_preserves_stable_thread_identity(database):
    async with database.unit_of_work() as uow:
        original = await uow.threads.get_or_create(
            SourceIdentity(
                provider="telegram",
                channel_id="-100123",
                channel_name="Old cats",
                channel_username="old_cats",
            )
        )

    async with database.unit_of_work() as uow:
        renamed = await uow.threads.get_or_create(
            SourceIdentity(
                provider="TELEGRAM",
                channel_id="-100123",
                channel_name="Renamed cats",
                channel_username="renamed_cats",
            )
        )

    assert renamed.id == original.id
    assert renamed.source.channel_name == "Renamed cats"
    assert renamed.source.channel_username == "renamed_cats"


@pytest.mark.parametrize("channel_name", ["Private cats", None])
async def test_removed_source_username_is_cleared_and_can_be_reassigned(database, channel_name):
    async with database.unit_of_work() as uow:
        original = await uow.threads.get_or_create(
            SourceIdentity("telegram", "-100123", "Public cats", "old_cats")
        )

    async with database.unit_of_work() as uow:
        private = await uow.threads.get_or_create(
            SourceIdentity("telegram", "-100123", channel_name, channel_username=None)
        )

    assert private.id == original.id
    assert private.source.channel_username is None
    assert private.source.channel_name == channel_name
    assert private.version == original.version

    # Check the committed snapshot from a fresh session, then simulate Telegram
    # assigning the removed handle to an unrelated stable channel ID.
    async with database.unit_of_work() as uow:
        stored = await uow.threads.get(original.id)
        assert stored is not None
        assert stored.source.channel_username is None
        assert stored.source.channel_name == channel_name
        reassigned = await uow.threads.get_or_create(
            SourceIdentity("telegram", "-100456", "Other cats", "old_cats")
        )
        public_again = await uow.threads.get_or_create(
            SourceIdentity("telegram", "-100123", "Public again", "new_cats")
        )

    assert reassigned.id != original.id
    assert public_again.id == original.id
    assert public_again.source.channel_username == "new_cats"
    async with database.unit_of_work() as uow:
        assert (await uow.threads.get(original.id)).source.channel_username == "new_cats"
        assert (await uow.threads.get(reassigned.id)).source.channel_username == "old_cats"


async def test_source_media_duplicates_are_independent_of_thread(database):
    async with database.unit_of_work() as uow:
        await uow.threads.get_or_create(SourceIdentity("telegram", "source-a"))
        await uow.threads.get_or_create(SourceIdentity("telegram", "source-b"))
        await uow.submissions.create(
            source_provider="youtube",
            source_media_id="same-video",
            source_channel_id="source-a",
        )
        with pytest.raises(DuplicateSourceMediaError):
            await uow.submissions.create(
                source_provider="YouTube",
                source_media_id="same-video",
                source_channel_id="source-b",
            )


async def test_two_source_threads_can_interleave_in_one_destination_chat(database):
    chat_id = -100999
    async with database.unit_of_work() as uow:
        first_thread = await uow.threads.get_or_create(
            SourceIdentity("telegram", "source-a", channel_name="Cats A")
        )
        second_thread = await uow.threads.get_or_create(
            SourceIdentity("telegram", "source-b", channel_name="Cats B")
        )
        first_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="video-a"
        )
        second_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="video-b"
        )
        first_post = await uow.threads.add_post(
            thread_id=first_thread.id, submission_id=first_submission.id
        )
        second_post = await uow.threads.add_post(
            thread_id=second_thread.id, submission_id=second_submission.id
        )
        first_thread = await uow.threads.initialize_root(
            thread_id=first_thread.id,
            post_id=first_post.id,
            expected_version=first_thread.version,
        )
        second_thread = await uow.threads.initialize_root(
            thread_id=second_thread.id,
            post_id=second_post.id,
            expected_version=second_thread.version,
        )
        await uow.projections.add_for_post(
            post_id=first_post.id,
            purpose="destination",
            reference=TelegramMessageRef(chat_id, 101),
        )
        await uow.projections.add_for_post(
            post_id=second_post.id,
            purpose="destination",
            reference=TelegramMessageRef(chat_id, 102),
        )

    assert first_thread.root_post_id == first_thread.tail_post_id == first_post.id
    assert second_thread.root_post_id == second_thread.tail_post_id == second_post.id
    async with database.unit_of_work() as uow:
        first_projection = await uow.projections.get_by_reference(TelegramMessageRef(chat_id, 101))
        second_projection = await uow.projections.get_by_reference(TelegramMessageRef(chat_id, 102))
        assert first_projection is not None and first_projection.post_id == first_post.id
        assert second_projection is not None and second_projection.post_id == second_post.id
        assert await uow.threads.contains_post(first_thread.id, first_post.id)
        assert not await uow.threads.contains_post(first_thread.id, second_post.id)


async def test_tail_update_detects_stale_version(database):
    async with database.unit_of_work() as uow:
        thread = await uow.threads.get_or_create(SourceIdentity("telegram", "source"))
        root_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="root"
        )
        root = await uow.threads.add_post(thread_id=thread.id, submission_id=root_submission.id)
        thread = await uow.threads.initialize_root(
            thread_id=thread.id, post_id=root.id, expected_version=thread.version
        )
        first_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="first-child"
        )
        stale_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="stale-child"
        )
        first_child = await uow.threads.add_post(
            thread_id=thread.id,
            submission_id=first_submission.id,
            parent_post_id=root.id,
        )
        stale_child = await uow.threads.add_post(
            thread_id=thread.id,
            submission_id=stale_submission.id,
            parent_post_id=root.id,
        )

    async with database.unit_of_work() as uow:
        advanced = await uow.threads.advance_tail(
            thread_id=thread.id,
            post_id=first_child.id,
            expected_tail_id=root.id,
            expected_version=thread.version,
        )
    assert advanced.tail_post_id == first_child.id

    with pytest.raises(ConcurrentThreadUpdateError):
        async with database.unit_of_work() as uow:
            await uow.threads.advance_tail(
                thread_id=thread.id,
                post_id=stale_child.id,
                expected_tail_id=root.id,
                expected_version=thread.version,
            )


async def test_cross_thread_parent_is_rejected(database):
    async with database.unit_of_work() as uow:
        first = await uow.threads.get_or_create(SourceIdentity("telegram", "first"))
        second = await uow.threads.get_or_create(SourceIdentity("telegram", "second"))
        parent_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="parent"
        )
        child_submission = await uow.submissions.create(
            source_provider="youtube", source_media_id="child"
        )
        parent = await uow.threads.add_post(thread_id=first.id, submission_id=parent_submission.id)
        with pytest.raises(CrossThreadParentError):
            await uow.threads.add_post(
                thread_id=second.id,
                submission_id=child_submission.id,
                parent_post_id=parent.id,
            )


async def test_telegram_coordinates_are_globally_unique(database):
    reference = TelegramMessageRef(chat_id=-100123, message_id=7)
    async with database.unit_of_work() as uow:
        first = await uow.submissions.create(
            source_provider="youtube", source_media_id="projection-a"
        )
        second = await uow.submissions.create(
            source_provider="youtube", source_media_id="projection-b"
        )
        await uow.projections.add_for_submission(
            submission_id=first.id, purpose="private", reference=reference
        )
        with pytest.raises(DuplicateTelegramMessageError):
            await uow.projections.add_for_submission(
                submission_id=second.id, purpose="moderation", reference=reference
            )


def test_initial_alembic_migration_builds_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", sqlite_url(database_path))

    command.upgrade(config, "head")
    command.check(config)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        submission_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(cat_video_submissions)")
        }
    assert {
        "cat_threads",
        "cat_video_submissions",
        "cat_posts",
        "telegram_message_refs",
        "media_handoff_requests",
        "post_intents",
        "reply_entry_tokens",
    } <= tables
    assert {
        "source_identity_status",
        "source_channel_name",
        "source_channel_username",
        "media_origin",
        "media_metadata",
        "validation_evidence",
        "provenance",
        "placement_mode",
        "selected_parent_post_id",
    } <= submission_columns
    assert revision == ("0005_durable_publication",)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_reply_migration_rollback_downgrade_and_retry(tmp_path, monkeypatch, failure):
    database_path = tmp_path / "reply-migration.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", sqlite_url(database_path))
    command.upgrade(config, "0002_source_aware_submissions")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO cat_video_submissions "
            "(id,source_provider,source_media_id,status) "
            "VALUES ('legacy','youtube','old','pending')"
        )
    create_table = Operations.create_table

    def fail_reply_table(operations, table_name, *args, **kwargs):
        result = create_table(operations, table_name, *args, **kwargs)
        if table_name == "reply_entry_tokens":
            raise failure("reply migration interrupted")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "create_table", fail_reply_table)
        with pytest.raises(failure, match="reply migration interrupted"):
            command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0002_source_aware_submissions",
        )
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master")}
        assert not tables & {"post_intents", "reply_entry_tokens"}
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "0002_source_aware_submissions")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT id FROM cat_video_submissions").fetchall() == [
            ("legacy",)
        ]
    command.upgrade(config, "head")
    command.check(config)


def test_intake_migration_preserves_legacy_submissions_and_downgrades(tmp_path, monkeypatch):
    database_path = tmp_path / "intake-migration.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", sqlite_url(database_path))
    command.upgrade(config, "0003_reply_chain_domain")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO cat_video_submissions "
            "(id,source_provider,source_media_id,status) "
            "VALUES ('legacy','youtube','old','pending')"
        )

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT placement_mode,selected_parent_post_id "
            "FROM cat_video_submissions WHERE id='legacy'"
        ).fetchone() == (None, None)

    command.downgrade(config, "0003_reply_chain_domain")
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(cat_video_submissions)")}
        assert "placement_mode" not in columns
        assert "selected_parent_post_id" not in columns
        assert connection.execute(
            "SELECT id FROM cat_video_submissions WHERE id='legacy'"
        ).fetchone() == ("legacy",)

    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_intake_migration_rolls_back_and_retries(tmp_path, monkeypatch, failure):
    database_path = tmp_path / "failed-intake-migration.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", sqlite_url(database_path))
    command.upgrade(config, "0003_reply_chain_domain")
    create_constraint = BatchOperations.create_check_constraint

    def fail_constraint(operations, constraint_name, condition, **kwargs):
        result = create_constraint(operations, constraint_name, condition, **kwargs)
        if constraint_name == "ck_cat_submissions_placement":
            raise failure("intake migration interrupted")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(BatchOperations, "create_check_constraint", fail_constraint)
        with pytest.raises(failure, match="intake migration interrupted"):
            command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(cat_video_submissions)")}
        assert "placement_mode" not in columns
        assert "selected_parent_post_id" not in columns
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0003_reply_chain_domain",
        )

    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_failed_sqlite_migration_rolls_back_ddl_and_can_be_retried(tmp_path, monkeypatch, failure):
    database_path = tmp_path / "failed-migration.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", sqlite_url(database_path))
    create_table = Operations.create_table

    def fail_after_second_table(operations, table_name, *args, **kwargs):
        result = create_table(operations, table_name, *args, **kwargs)
        if table_name == "cat_video_submissions":
            raise failure("migration interrupted")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "create_table", fail_after_second_table)
        with pytest.raises(failure, match="migration interrupted"):
            command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert not tables & {
            "cat_threads",
            "cat_video_submissions",
            "cat_posts",
            "telegram_message_refs",
        }
        if "alembic_version" in tables:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == []

    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0005_durable_publication",
        )


def test_failed_second_migration_rolls_back_and_can_be_retried(tmp_path, monkeypatch):
    database_path = tmp_path / "failed-second-migration.sqlite3"
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", sqlite_url(database_path))
    command.upgrade(config, "0001_persistence_foundation")
    add_column = Operations.add_column

    def fail_after_second_column(operations, table_name, column, **kwargs):
        result = add_column(operations, table_name, column, **kwargs)
        if column.name == "source_channel_username":
            raise RuntimeError("second migration interrupted")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "add_column", fail_after_second_column)
        with pytest.raises(RuntimeError, match="second migration interrupted"):
            command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(cat_video_submissions)")}
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "source_channel_name" not in columns
        assert "source_channel_username" not in columns
        assert "media_handoff_requests" not in tables
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0001_persistence_foundation",
        )

    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("abort", [False, True], ids=["commit", "rollback"])
async def test_repositories_cannot_escape_unit_of_work(database, abort):
    uow = database.unit_of_work()

    with pytest.raises(RuntimeError, match="abort") if abort else nullcontext():
        async with uow:
            submission = await uow.submissions.create(
                source_provider="youtube", source_media_id="owned"
            )
            repositories = (uow.submissions, uow.threads, uow.projections)
            submission_id = submission.id
            if abort:
                raise RuntimeError("abort")
    submissions, threads, projections = repositories

    # Every retained repository must fail for reads and writes, before a new
    # implicit transaction can take ownership of another pooled connection.
    operations = [
        lambda: submissions.get_by_source_media("youtube", "owned"),
        lambda: submissions.create(source_provider="youtube", source_media_id="escaped"),
        lambda: threads.get("missing"),
        lambda: threads.get_or_create(SourceIdentity("telegram", "escaped")),
        lambda: projections.get_by_reference(TelegramMessageRef(-100123, 1)),
        lambda: projections.add_for_submission(
            submission_id=submission_id,
            purpose="private",
            reference=TelegramMessageRef(-100123, 1),
        ),
    ]
    for operation in operations:
        with pytest.raises(InvalidRequestError, match="permanently closed"):
            await operation()

    assert uow._session is None
    assert uow._transaction is None
    for name in ("submissions", "threads", "projections"):
        with pytest.raises(RuntimeError, match="not active"):
            getattr(uow, name)

    # Re-entering the same UoW gets a fresh session; old repositories stay closed.
    async with uow:
        assert uow.submissions is not submissions
        assert await uow.submissions.get_by_source_media("youtube", "escaped") is None
        assert (await uow.submissions.get_by_source_media("youtube", "owned") is None) == abort


async def test_active_unit_of_work_cannot_be_reentered(database):
    uow = database.unit_of_work()
    async with uow:
        repository = uow.submissions
        with pytest.raises(RuntimeError, match="already active"):
            await uow.__aenter__()
        assert uow.submissions is repository
        await repository.create(source_provider="youtube", source_media_id="still-owned")

    async with database.unit_of_work() as check:
        assert await check.submissions.get_by_source_media("youtube", "still-owned") is not None
