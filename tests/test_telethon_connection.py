from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cats_channel.adapters.telethon_connection import (
    TelethonConnectionMiddleware,
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
