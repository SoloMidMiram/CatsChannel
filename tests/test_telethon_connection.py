import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cats_channel.adapters.telethon_connection import (
    TelethonConnectionMiddleware,
    cancellable,
    translate_telethon_error,
)
from cats_channel.errors import MediaError


def client_with(**overrides):
    values = {
        "connect": AsyncMock(),
        "disconnect": AsyncMock(),
        "is_user_authorized": AsyncMock(return_value=True),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_middleware_owns_connection_operations_and_disconnect():
    client = client_with()
    middleware = TelethonConnectionMiddleware(client)
    async with middleware:
        assert (
            await middleware.call("authorization", client.is_user_authorized(), timeout=1) is True
        )
    assert middleware.snapshot() == {
        "connection_attempts": 1,
        "operation_attempts": 2,
        "automatic_retries": 0,
        "completed_phases": ["connection", "authorization", "disconnect"],
        "failed_phase": None,
        "cleanup_failed_phase": None,
        "cleanup_pending": False,
    }
    client.connect.assert_awaited_once()
    client.disconnect.assert_awaited_once()


async def test_connection_error_is_classified_once_and_client_is_disconnected():
    proxy_error = type("ProxyConnectionError", (Exception,), {})
    client = client_with(connect=AsyncMock(side_effect=proxy_error("private proxy URL")))
    middleware = TelethonConnectionMiddleware(client)
    with pytest.raises(MediaError) as raised:
        async with middleware:
            pytest.fail("A failed connection must not enter the operation body")
    assert raised.value.code == "telegram_connect"
    assert raised.value.log_analysis["phase"] == "connection"
    assert raised.value.log_analysis["connection_attempts"] == 1
    assert raised.value.log_analysis["operation_attempts"] == 1
    assert raised.value.log_analysis["automatic_retries"] == 0
    assert "private" not in str(raised.value.log_analysis)
    client.connect.assert_awaited_once()
    client.disconnect.assert_awaited_once()


async def test_nested_operation_error_uses_inner_exception_pattern():
    proxy_error = type("ProxyConnectionError", (Exception,), {})

    async def wrapped_failure():
        try:
            raise proxy_error("private route")
        except proxy_error as error:
            raise RuntimeError("private wrapper") from error

    client = client_with()
    middleware = TelethonConnectionMiddleware(client)
    with pytest.raises(MediaError) as raised:
        async with middleware:
            await middleware.call("bot_resolution", wrapped_failure(), timeout=1)
    assert raised.value.code == "telegram_connect"
    assert raised.value.log_analysis["phase"] == "bot_resolution"
    assert raised.value.log_analysis["exception_types"] == [
        "RuntimeError",
        "ProxyConnectionError",
    ]
    assert middleware.snapshot()["failed_phase"] == "bot_resolution"


async def test_disconnect_failure_preserves_primary_error_as_warning():
    client = client_with(disconnect=AsyncMock(side_effect=OSError("private disconnect")))
    middleware = TelethonConnectionMiddleware(client)
    with pytest.raises(MediaError) as raised:
        async with middleware:
            raise middleware.expected_error("telegram_login", phase="authorization")
    assert raised.value.code == "telegram_login"
    assert raised.value.warnings == ("telegram_disconnect_failed",)


async def test_disconnect_failure_after_success_is_cleanup_error():
    client = client_with(disconnect=AsyncMock(side_effect=OSError("private disconnect")))
    middleware = TelethonConnectionMiddleware(client)
    with pytest.raises(MediaError) as raised:
        async with middleware:
            pass
    assert raised.value.code == "cleanup_failed"
    assert raised.value.log_analysis["phase"] == "disconnect"


async def test_operation_timeout_has_one_bounded_drain_budget():
    finished = asyncio.Event()

    async def ignores_cancellation_temporarily():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.3)
            raise
        finally:
            finished.set()

    started = time.monotonic()
    with pytest.raises(MediaError) as raised:
        await cancellable(
            ignores_cancellation_temporarily(),
            None,
            0.02,
            shutdown_timeout=0.02,
        )
    elapsed = time.monotonic() - started
    assert raised.value.code == "timeout"
    assert raised.value.warnings == ("telegram_operation_cleanup_pending",)
    assert elapsed < 0.2
    await asyncio.wait_for(finished.wait(), timeout=1)


async def test_cancelled_real_disconnect_does_not_claim_resource_closure():
    class ShieldedClient:
        def __init__(self):
            self.disconnect_wrapper_calls = 0
            self.session_closed = False

        async def connect(self):
            return None

        def disconnect(self):
            self.disconnect_wrapper_calls += 1
            return asyncio.shield(asyncio.create_task(self._disconnect_coro()))

        async def _disconnect_coro(self):
            await asyncio.sleep(10)
            self.session_closed = True

    client = ShieldedClient()
    middleware = TelethonConnectionMiddleware(client, disconnect_timeout=0.02)
    with pytest.raises(MediaError) as raised:
        async with middleware:
            pass
    assert raised.value.code == "cleanup_failed"
    assert raised.value.warnings == ("telegram_cleanup_pending",)
    assert client.disconnect_wrapper_calls == 0
    assert client.session_closed is False
    assert middleware.cleanup_pending is True
    assert middleware._closed is False


async def test_self_cancelled_disconnect_is_also_unconfirmed():
    class SelfCancellingClient:
        def __init__(self):
            self.session_closed = False

        async def connect(self):
            return None

        async def _disconnect_coro(self):
            raise asyncio.CancelledError

    client = SelfCancellingClient()
    middleware = TelethonConnectionMiddleware(client)
    with pytest.raises(MediaError) as raised:
        async with middleware:
            pass
    assert raised.value.code == "cleanup_failed"
    assert raised.value.warnings == ("telegram_cleanup_pending",)
    assert client.session_closed is False
    assert middleware.cleanup_pending is True
    assert middleware._closed is False


async def test_unknown_shielded_disconnect_is_reported_pending_and_bounded():
    class ShieldOnlyClient:
        def __init__(self):
            self.cleanup_finished = asyncio.Event()

        async def connect(self):
            return None

        def disconnect(self):
            async def cleanup():
                try:
                    await asyncio.sleep(0.3)
                finally:
                    self.cleanup_finished.set()

            return asyncio.shield(asyncio.create_task(cleanup()))

    client = ShieldOnlyClient()
    middleware = TelethonConnectionMiddleware(client, disconnect_timeout=0.02)
    started = time.monotonic()
    with pytest.raises(MediaError) as raised:
        async with middleware:
            pass
    assert time.monotonic() - started < 0.2
    assert raised.value.code == "cleanup_failed"
    assert raised.value.warnings == ("telegram_cleanup_pending",)
    assert middleware.cleanup_pending is True
    assert middleware._closed is False
    await asyncio.wait_for(client.cleanup_finished.wait(), timeout=1)


async def test_repeated_cancellation_cannot_orphan_owned_disconnect():
    class SlowCancellationClient:
        def __init__(self):
            self.cleanup_started = asyncio.Event()
            self.cancellation_seen = asyncio.Event()
            self.release = asyncio.Event()
            self.cleanup_finished = asyncio.Event()

        async def connect(self):
            return None

        async def _disconnect_coro(self):
            self.cleanup_started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancellation_seen.set()
                await self.release.wait()
                raise
            finally:
                self.cleanup_finished.set()

    client = SlowCancellationClient()
    middleware = TelethonConnectionMiddleware(client, disconnect_timeout=1)

    async def use_client():
        async with middleware:
            pass

    task = asyncio.create_task(use_client())
    await asyncio.wait_for(client.cleanup_started.wait(), timeout=1)
    task.cancel()
    await asyncio.wait_for(client.cancellation_seen.wait(), timeout=1)
    task.cancel()
    client.release.set()
    with pytest.raises(MediaError) as raised:
        await task
    assert raised.value.code == "cancelled"
    assert raised.value.warnings == ("telegram_cleanup_pending",)
    assert client.cleanup_finished.is_set()
    assert middleware.cleanup_pending is True
    assert middleware._closed is False


@pytest.mark.parametrize(
    ("exception_name", "code"),
    [
        ("OperationalError", "telegram_session_io"),
        ("ServerError", "telegram_server"),
        ("AuthRestartError", "telegram_login"),
        ("IncompleteReadError", "telegram_connect"),
    ],
)
def test_additional_observed_error_families_are_classified(exception_name, code):
    error_type = type(exception_name, (Exception,), {})
    translated = translate_telethon_error(error_type("private detail"), phase="connection")
    assert translated.code == code
    assert translated.log_analysis["exception_types"] == [exception_name]
    assert translated.log_analysis["raw_log_included"] is False
