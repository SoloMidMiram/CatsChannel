import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, GetUpdates
from aiogram.types import User
from test_bot_application import BOT_TOKEN, RecordingSession, settings, update

from cats_channel.bot import create_bot_application


class PollingSession(RecordingSession):
    def __init__(self):
        super().__init__()
        self.polling = asyncio.Event()
        self.close_count = 0

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return User(id=bot.id, is_bot=True, first_name="Cats", username="cats_test_bot")
        if isinstance(method, GetUpdates):
            self.polling.set()
            await asyncio.Event().wait()
        return await super().make_request(bot, method, timeout)

    async def close(self):
        self.close_count += 1
        await super().close()


class Storage(MemoryStorage):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.close_count = 0

    async def close(self):
        self.close_count += 1
        self.events.append("storage:close")


def application(*, resources=(), service=None, startup_sleep=asyncio.sleep, **setting_updates):
    events = []
    session = PollingSession()
    storage = Storage(events)
    app = create_bot_application(
        settings(**setting_updates),
        bot=Bot(BOT_TOKEN, session=session),
        storage=storage,
        resources=resources,
        media_service=service or AsyncMock(),
        startup_sleep=startup_sleep,
    )
    return app, session, storage, events


async def test_startup_get_me_recovers_with_bounded_read_only_retries(capsys):
    sleep = AsyncMock()
    app, session, storage, _ = application(
        startup_sleep=sleep,
        bot_api_startup_attempts=3,
        bot_api_startup_backoff_seconds=0.5,
    )
    original_request = session.make_request
    attempts = 0

    async def flaky_get_me(bot, method, timeout=None):
        nonlocal attempts
        if isinstance(method, GetMe):
            attempts += 1
            if attempts < 3:
                raise TelegramNetworkError(method=method, message="token=private")
        return await original_request(bot, method, timeout)

    session.make_request = flaky_get_me
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    await app.dispatcher.stop_polling()
    await running

    assert attempts == 3
    assert [call.args for call in sleep.await_args_list] == [(0.5,), (1.0,)]
    assert session.close_count == storage.close_count == 1
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    retries = [record for record in records if record["event"] == "bot_startup_retry"]
    assert [record["analysis"]["operation_attempts"] for record in retries] == [1, 2]
    assert all(record["analysis"]["phase"] == "bot_api_get_me" for record in retries)
    assert "private" not in json.dumps(records)


async def test_startup_get_me_stops_at_bound_and_reports_exact_phase(capsys):
    sleep = AsyncMock()
    app, session, storage, _ = application(
        startup_sleep=sleep,
        bot_api_startup_attempts=3,
        bot_api_startup_backoff_seconds=0,
    )
    attempts = 0

    async def fail_get_me(bot, method, timeout=None):
        nonlocal attempts
        attempts += 1
        raise TelegramNetworkError(method=method, message="token=private")

    session.make_request = fail_get_me
    with pytest.raises(TelegramNetworkError):
        await app.start_polling()

    assert attempts == 3
    assert sleep.await_count == 2
    assert session.close_count == storage.close_count == 1
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    final = next(record for record in records if record["event"] == "bot_lifecycle_failure")
    assert final["code"] == "bot_api_network"
    assert final["analysis"]["phase"] == "bot_api_get_me"
    assert final["analysis"]["operation_attempts"] == 3
    assert final["analysis"]["automatic_retries"] == 2
    assert "private" not in json.dumps(records)


async def test_startup_timeout_without_method_still_reports_get_me_phase(capsys):
    app, session, storage, _ = application(bot_api_startup_attempts=1)

    async def time_out(bot, method, timeout=None):
        raise TimeoutError("token=private")

    session.make_request = time_out
    with pytest.raises(TelegramNetworkError):
        await app.start_polling()

    assert session.close_count == storage.close_count == 1
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    final = next(record for record in records if record["event"] == "bot_lifecycle_failure")
    assert final["analysis"]["phase"] == "bot_api_get_me"
    assert final["analysis"]["operation_attempts"] == 1
    assert final["code"] == "bot_api_network"
    assert "private" not in json.dumps(records)


@pytest.mark.parametrize("phase", ["resource", "database_recovery", "shutdown"])
async def test_non_bot_api_timeouts_remain_internal_and_close_owned_resources(phase, capsys):
    error = TimeoutError("private-database-or-shutdown")

    @asynccontextmanager
    async def resource():
        raise error
        yield

    app, session, storage, _ = application(resources=(resource,) if phase == "resource" else ())

    async def fail():
        raise error

    if phase == "database_recovery":
        app.dispatcher.startup.register(fail)
    elif phase == "shutdown":
        app.dispatcher.shutdown.register(fail)

    running = asyncio.create_task(app.start_polling())
    if phase == "shutdown":
        await asyncio.wait_for(session.polling.wait(), 2)
        await app.dispatcher.stop_polling()
    with pytest.raises(TimeoutError) as caught:
        await running

    assert caught.value is error
    assert session.close_count == storage.close_count == 1
    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    failures = [record for record in records if record["event"] == "bot_lifecycle_failure"]
    assert failures
    assert all(record["code"] == "internal_error" for record in failures)
    assert all(record["analysis"]["phase"] == "bot_lifecycle" for record in failures)
    assert "private-database-or-shutdown" not in output


async def test_factory_does_not_enter_resources_or_call_bot_api():
    factory = AsyncMock()
    app, session, _, _ = application(resources=(factory,))
    factory.assert_not_called()
    assert session.methods == [] and not session.polling.is_set()
    assert app.bot.session is session


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_persistent_run_bot_owns_database_and_preserves_startup_failure(
    monkeypatch, cleanup_fails
):
    from cats_channel import persistence
    from cats_channel.bot import application as application_module

    database = AsyncMock()

    @asynccontextmanager
    async def startup_uow():
        uow = AsyncMock()
        uow.publications.list_sending.return_value = ()
        yield uow

    database.unit_of_work = startup_uow
    if cleanup_fails:
        database.dispose.side_effect = RuntimeError("database close failed")

    class Owner:
        @classmethod
        def from_settings(cls, _settings):
            return database

    monkeypatch.setitem(persistence.__dict__, "Database", Owner)
    session = PollingSession()
    original = application_module.create_bot_application
    startup_error = RuntimeError("startup failed")

    async def fail_startup():
        raise startup_error

    def create(*args, **kwargs):
        app = original(*args, bot=Bot(BOT_TOKEN, session=session), **kwargs)
        app.dispatcher.startup.register(fail_startup)
        return app

    monkeypatch.setattr(application_module, "create_bot_application", create)
    # This test isolates startup-hook/cleanup ownership; isolation has its own
    # real lifecycle tests. Supply valid config and stub only the read-only probe.
    monkeypatch.setattr(application_module, "verify_review_isolation", AsyncMock())
    with pytest.raises(RuntimeError) as caught:
        await application_module.run_bot(
            settings(reply_entries_enabled=True, review_channel_id=-100456)
        )
    assert caught.value is startup_error
    if cleanup_fails:
        assert str(caught.value.__cause__) == "database close failed"
    database.dispose.assert_awaited_once()
    assert session.close_count == 1


async def test_persistent_composition_failure_remains_primary_when_database_close_fails(
    monkeypatch,
):
    from cats_channel import persistence
    from cats_channel.bot.application import run_bot

    database = AsyncMock()
    database.dispose.side_effect = RuntimeError("database close failed")

    class Owner:
        @classmethod
        def from_settings(cls, _settings):
            return database

    monkeypatch.setitem(persistence.__dict__, "Database", Owner)
    with pytest.raises(ValueError, match="numeric CHANNEL_ID") as caught:
        await run_bot(settings(reply_entries_enabled=True, channel_id="@unresolved"))
    assert str(caught.value.__cause__) == "database close failed"
    database.dispose.assert_awaited_once()


async def test_real_polling_closes_owned_resources_once_in_reverse_order():
    events = []

    @asynccontextmanager
    async def first():
        events.append("first:open")
        try:
            yield
        finally:
            events.append("first:close")

    @asynccontextmanager
    async def second():
        events.append("second:open")
        try:
            yield
        finally:
            events.append("second:close")

    app, session, storage, _ = application(resources=(first, second))
    shutdown = AsyncMock()

    async def on_shutdown():
        await shutdown()

    app.dispatcher.shutdown.register(on_shutdown)
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    await asyncio.wait_for(app.dispatcher.stop_polling(), 2)
    await asyncio.wait_for(running, 2)
    assert events == ["first:open", "second:open", "second:close", "first:close"]
    assert session.close_count == storage.close_count == 1
    shutdown.assert_awaited_once()
    with pytest.raises(RuntimeError, match="already been started"):
        await app.start_polling()


async def test_startup_failure_closes_resources_and_logs_without_raw_exception(capsys):
    app, session, storage, _ = application()

    async def fail():
        raise RuntimeError("private-token-body")

    app.dispatcher.startup.register(fail)
    with pytest.raises(RuntimeError):
        await app.start_polling()
    assert session.close_count == storage.close_count == 1
    output = capsys.readouterr().err
    assert "bot_lifecycle_failure" in output
    assert "private-token-body" not in output


async def test_partial_resource_acquisition_unwinds_and_closes_bot():
    events = []

    @asynccontextmanager
    async def first():
        events.append("open")
        try:
            yield
        finally:
            events.append("close")

    @asynccontextmanager
    async def failure():
        raise RuntimeError("startup failed")
        yield

    app, session, storage, _ = application(resources=(first, failure))
    with pytest.raises(RuntimeError, match="startup failed"):
        await app.start_polling()
    assert events == ["open", "close"]
    assert session.close_count == storage.close_count == 1


async def test_startup_failure_remains_primary_when_resource_cleanup_also_fails():
    @asynccontextmanager
    async def resource():
        try:
            yield
        finally:
            raise RuntimeError("resource cleanup failed")

    app, session, storage, _ = application(resources=(resource,))

    async def fail_startup():
        raise RuntimeError("startup failed")

    app.dispatcher.startup.register(fail_startup)
    with pytest.raises(RuntimeError, match="startup failed") as caught:
        await app.start_polling()

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "resource cleanup failed"
    assert session.close_count == storage.close_count == 1


async def test_cancellation_during_startup_unwinds_owned_resources():
    started = asyncio.Event()
    app, session, storage, _ = application()

    async def startup():
        started.set()
        await asyncio.Event().wait()

    app.dispatcher.startup.register(startup)
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(started.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    assert session.close_count == storage.close_count == 1


async def test_repeated_cancellation_waits_for_active_update_cleanup_before_storage_close():
    started, cancelling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    events = []

    class BlockingMedia:
        async def probe_async(self, url):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                await release.wait()
                events.append("worker:closed")

    app, session, storage, _ = application(service=BlockingMedia())
    storage.events = events
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    feeding = asyncio.create_task(
        app.dispatcher.feed_update(app.bot, update("/probe https://youtu.be/abcdefghijk"))
    )
    await asyncio.wait_for(started.wait(), 2)
    running.cancel()
    await asyncio.wait_for(cancelling.wait(), 2)
    running.cancel()
    await asyncio.sleep(0)
    assert not running.done() and not session.closed and storage.close_count == 0
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    with pytest.raises(asyncio.CancelledError):
        await feeding
    assert events == ["worker:closed", "storage:close"]
    assert app.dispatcher.active_update_count == app.flow_coordinator.pending_count == 0
    assert session.close_count == storage.close_count == 1


async def test_cleanup_failure_still_closes_remaining_resources_and_bot():
    events = []

    @asynccontextmanager
    async def outer():
        try:
            yield
        finally:
            events.append("outer:closed")

    @asynccontextmanager
    async def failure():
        try:
            yield
        finally:
            raise RuntimeError("close failed")

    app, session, storage, _ = application(resources=(outer, failure))
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    await app.dispatcher.stop_polling()
    with pytest.raises(RuntimeError, match="close failed"):
        await running
    assert events == ["outer:closed"]
    assert session.close_count == storage.close_count == 1


@pytest.mark.parametrize("fail_close", [False, True])
async def test_repeated_cancellation_during_resource_close_waits_and_preserves_cancellation(
    fail_close, capsys
):
    closing, release = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def resource():
        try:
            yield
        finally:
            closing.set()
            await release.wait()
            if fail_close:
                raise RuntimeError("private-cleanup-body")

    app, session, storage, _ = application(resources=(resource,))
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    await app.dispatcher.stop_polling()
    await asyncio.wait_for(closing.wait(), 2)
    running.cancel()
    await asyncio.sleep(0)
    running.cancel()
    await asyncio.sleep(0)
    assert not running.done() and not session.closed
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    assert session.close_count == storage.close_count == 1
    output = capsys.readouterr().err
    assert "private-cleanup-body" not in output
    if fail_close:
        assert "bot_lifecycle_failure" in output


async def test_shutdown_callback_failure_still_closes_bot():
    app, session, storage, _ = application()

    async def fail_shutdown():
        raise RuntimeError("shutdown failed")

    app.dispatcher.shutdown.register(fail_shutdown)
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    assert session.close_count == storage.close_count == 1


async def test_normal_stop_preserves_shutdown_failure_without_a_self_cause():
    app, session, storage, _ = application()

    async def fail_shutdown():
        raise RuntimeError("shutdown failed")

    app.dispatcher.shutdown.register(fail_shutdown)
    running = asyncio.create_task(app.start_polling())
    await asyncio.wait_for(session.polling.wait(), 2)
    await app.dispatcher.stop_polling()
    with pytest.raises(RuntimeError, match="shutdown failed") as caught:
        await running

    assert caught.value.__cause__ is not caught.value
    assert session.close_count == storage.close_count == 1


@pytest.mark.parametrize("fail_shutdown", [False, True])
@pytest.mark.parametrize("cancel_polling", [False, True])
async def test_real_polling_failure_remains_primary_across_shutdown(
    fail_shutdown, cancel_polling, capsys
):
    app, session, storage, _ = application()
    polling_error = (
        asyncio.CancelledError("private-polling-body")
        if cancel_polling
        else RuntimeError("private-polling-body")
    )
    shutdown_error = RuntimeError("private-shutdown-body")
    shutdown_count = 0
    original_request = session.make_request

    async def fail_get_me(bot, method, timeout=None):
        if isinstance(method, GetMe):
            raise polling_error
        return await original_request(bot, method, timeout)

    async def shutdown():
        nonlocal shutdown_count
        shutdown_count += 1
        if fail_shutdown:
            raise shutdown_error

    session.make_request = fail_get_me
    app.dispatcher.shutdown.register(shutdown)
    with pytest.raises(type(polling_error)) as caught:
        await asyncio.wait_for(app.start_polling(), 2)

    # asyncio.shield can synthesize a new CancelledError for a cancelled task.
    if not cancel_polling:
        assert caught.value is polling_error
    if fail_shutdown:
        assert caught.value.__cause__ is shutdown_error
    assert shutdown_count == session.close_count == storage.close_count == 1
    assert app.dispatcher.active_update_count == 0
    output = capsys.readouterr().err
    assert "private-polling-body" not in output
    assert "private-shutdown-body" not in output


async def test_legacy_polling_bot_is_borrowed_while_factory_bot_is_owned():
    app, owned_session, storage, _ = application()
    borrowed_session = PollingSession()
    borrowed_bot = Bot(BOT_TOKEN, session=borrowed_session)
    running = asyncio.create_task(app.start_polling(borrowed_bot))
    await asyncio.wait_for(borrowed_session.polling.wait(), 2)
    await app.dispatcher.stop_polling()
    await running
    assert owned_session.close_count == storage.close_count == 1
    assert borrowed_session.close_count == 0
    await borrowed_session.close()
