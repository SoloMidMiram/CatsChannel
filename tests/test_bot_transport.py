"""Explicit transport, real local SOCKS routing, and read-only preflight contracts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.methods import GetMe, GetUpdates, SendVideo
from aiogram.utils.backoff import Backoff
from aiohttp_socks import ProxyConnector
from test_bot_application import settings, update

from cats_channel.bot import create_bot_application
from cats_channel.bot.preflight import diagnose_bot_api
from cats_channel.bot.transport import create_configured_bot
from cats_channel.config import Settings
from cats_channel.diagnostics import configure_logging


@pytest.mark.parametrize(
    "scheme,normalized",
    [
        ("socks5h", "socks5"),
        ("socks5", "socks5"),
        ("socks4a", "socks4"),
        ("socks4", "socks4"),
        ("http", "http"),
    ],
)
async def test_explicit_proxy_uses_socks_connector_and_remote_dns(scheme, normalized):
    bot = create_configured_bot(
        settings(bot_api_proxy=f"{scheme}://127.0.0.1:10808", bot_api_timeout_seconds=17)
    )
    assert bot.session.proxy.rstrip("/") == f"{normalized}://127.0.0.1:10808"
    assert bot.session._connector_type is ProxyConnector
    assert bot.session._connector_init["rdns"] is True
    assert bot.session.timeout == 17
    await bot.session.close()


async def test_direct_is_explicit_and_does_not_reuse_other_backend_proxy(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    bot = create_configured_bot(
        settings(
            telegram_proxy="socks5h://127.0.0.1:10808", youtube_proxy="socks5h://127.0.0.1:10808"
        )
    )
    assert bot.session.proxy is None
    await bot.session.close()


async def test_disabled_proxy_makes_real_request_directly(monkeypatch):
    observed = []
    tasks = set()

    async def api(reader, writer):
        tasks.add(asyncio.current_task())
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            observed.append(request.split(b"\r\n", 1)[0])
            data = json.dumps(
                {"ok": True, "result": {"id": 123456, "is_bot": True, "first_name": "Test"}}
            ).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                + str(len(data)).encode()
                + b"\r\n\r\n"
                + data
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("BOT_API_PROXY_ENABLED", "false")
    configuration = settings(bot_api_proxy="socks5h://127.0.0.1:1")
    assert configuration.bot_api_proxy is not None
    assert configuration.effective_bot_api_proxy is None
    bot = create_configured_bot(configuration)
    server = await asyncio.start_server(api, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    bot.session.api = TelegramAPIServer.from_base(f"http://127.0.0.1:{port}")
    try:
        async with server:
            assert (await asyncio.wait_for(bot.get_me(), 5)).id == 123456
        assert len(observed) == 1
        assert observed[0].startswith(b"POST /bot123456:TEST_TOKEN/getMe ")
    finally:
        await bot.session.close()
        if tasks:
            await asyncio.gather(*tasks)


async def test_preflight_reports_disabled_saved_proxy():
    report = await diagnose_bot_api(
        settings(bot_api_proxy="http://127.0.0.1:10808", bot_api_proxy_enabled=False),
        bot=fake_bot(),
    )
    assert report["proxy_configured"] is True
    assert report["proxy_enabled"] is False
    assert report["proxy_in_use"] is False
    assert report["proxy_scheme"] is None


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:10808",
        "socks5://user:secret@127.0.0.1:10808",
        "socks5://127.0.0.1",
        "socks5://127.0.0.1:10808/path",
        "http://127.0.0.1:10808?token=secret",
    ],
)
def test_proxy_configuration_rejects_unsupported_or_sensitive_origins(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, bot_api_proxy=value)


async def test_application_uses_configured_session_but_preserves_injected_bot():
    app = create_bot_application(settings(bot_api_proxy="socks5h://127.0.0.1:10808"))
    assert app.bot.session.proxy.startswith("socks5://")
    await app.bot.session.close()
    injected = create_configured_bot(settings())
    app = create_bot_application(settings(bot_api_proxy="socks5h://127.0.0.1:10808"), bot=injected)
    assert app.bot is injected and app.bot.session.proxy is None
    await injected.session.close()


@pytest.mark.parametrize("reject", [False, True])
async def test_real_bot_api_request_crosses_socks_without_local_dns_or_retry(reject):
    observed = []
    tasks = set()

    async def proxy(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            version, methods = await reader.readexactly(2)
            assert version == 5
            await reader.readexactly(methods)
            writer.write(b"\x05\x00")
            await writer.drain()
            version, command, _, address_type = await reader.readexactly(4)
            assert (version, command, address_type) == (5, 1, 3)
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode()
            port = int.from_bytes(await reader.readexactly(2), "big")
            observed.append((host, port))
            writer.write(
                b"\x05" + (b"\x02" if reject else b"\x00") + b"\x00\x01\x7f\x00\x00\x01\x00\x50"
            )
            await writer.drain()
            if not reject:
                request = await reader.readuntil(b"\r\n\r\n")
                assert request.startswith(b"POST /bot123456:TEST_TOKEN/getMe ")
                data = json.dumps(
                    {"ok": True, "result": {"id": 123456, "is_bot": True, "first_name": "Test"}}
                ).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                    + str(len(data)).encode()
                    + b"\r\n\r\n"
                    + data
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(proxy, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    bot = create_configured_bot(settings(bot_api_proxy=f"socks5h://127.0.0.1:{port}"))
    bot.session.api = TelegramAPIServer.from_base("http://bot-api.invalid:8080")
    try:
        async with server:
            if reject:
                with pytest.raises(TelegramNetworkError):
                    await asyncio.wait_for(bot.get_me(), 5)
            else:
                assert (await asyncio.wait_for(bot.get_me(), 5)).id == 123456
            assert observed == [("bot-api.invalid", 8080)]
    finally:
        await bot.session.close()
        if tasks:
            await asyncio.gather(*tasks)


def fake_bot(*, webhook=False, public=False, can_post=True):
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(id=123456)
    bot.get_webhook_info.return_value = SimpleNamespace(
        url="https://private/token" if webhook else "", pending_update_count=0
    )
    bot.get_chat.return_value = SimpleNamespace(
        type="channel", username="public" if public else None
    )
    bot.get_chat_member.return_value = SimpleNamespace(
        status="administrator", can_post_messages=can_post, can_edit_messages=True
    )
    return bot


async def test_preflight_checks_permissions_and_webhook_without_mutation():
    bot = fake_bot()
    report = await diagnose_bot_api(settings(reply_entries_enabled=True), bot=bot)
    assert report["status"] == "ready" and report["private_channel"] is True
    assert report["private_pilot_ready"] is True
    assert report["webhook"] == "absent" and report["can_post_messages"] is True
    assert report["publishing"] == "not_attempted"
    assert [call[0] for call in bot.mock_calls] == [
        "get_me",
        "get_webhook_info",
        "get_chat",
        "get_chat_member",
    ]


@pytest.mark.parametrize(
    "webhook,enabled,can_post", [(True, True, True), (False, False, True), (False, True, False)]
)
async def test_preflight_reports_blockers_without_deleting_webhook(webhook, enabled, can_post):
    bot = fake_bot(webhook=webhook, can_post=can_post)
    report = await diagnose_bot_api(settings(reply_entries_enabled=enabled), bot=bot)
    assert report["status"] == "blocked"
    assert "private/token" not in json.dumps(report)
    bot.delete_webhook.assert_not_awaited()
    bot.send_video.assert_not_awaited()


async def test_public_channel_is_not_a_private_pilot_target():
    report = await diagnose_bot_api(settings(reply_entries_enabled=True), bot=fake_bot(public=True))
    assert report["private_channel"] is False and report["private_pilot_ready"] is False


@pytest.mark.parametrize(
    "error,category",
    [
        (
            TelegramNetworkError(method=GetMe(), message="https://api.telegram.org/botSECRET"),
            "bot_api_network",
        ),
        (TelegramUnauthorizedError(method=GetMe(), message="SECRET"), "bot_api_unauthorized"),
        (TimeoutError("SECRET"), "bot_api_network"),
    ],
)
async def test_preflight_contains_transport_errors_without_retry_or_secret_output(error, category):
    bot = fake_bot()
    bot.get_me.side_effect = error
    report = await diagnose_bot_api(settings(), bot=bot)
    assert report["status"] == "blocked" and report["error_category"] == category
    assert "SECRET" not in json.dumps(report)
    assert bot.get_me.await_count == 1


async def test_owned_preflight_closes_session_and_cancellation_propagates(monkeypatch):
    bot = fake_bot()
    monkeypatch.setattr("cats_channel.bot.preflight.create_configured_bot", lambda _: bot)
    await diagnose_bot_api(settings(reply_entries_enabled=True))
    bot.session.close.assert_awaited_once()
    bot.get_me.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await diagnose_bot_api(settings())
    assert bot.session.close.await_count == 2


@pytest.mark.parametrize(
    "error,category",
    [
        (TelegramNetworkError(method=GetMe(), message="token=private"), "bot_api_network"),
        (TimeoutError("token=private"), "internal_error"),
    ],
)
def test_bot_cli_classifies_only_owned_bot_api_failures(monkeypatch, capsys, error, category):
    import sys

    from cats_channel.cli import main

    run = AsyncMock(side_effect=error)
    monkeypatch.setattr("cats_channel.bot.run_bot", run)
    monkeypatch.setattr("cats_channel.cli.Settings", lambda: settings())
    monkeypatch.setattr(sys, "argv", ["cats-channel", "--bot"])

    assert main() == 1
    output = capsys.readouterr()
    response = json.loads(output.out)
    record = json.loads(output.err)
    assert response["error"]["code"] == record["code"] == category
    expected_phase = (
        "bot_api_get_me" if isinstance(error, TelegramNetworkError) else "bot_lifecycle"
    )
    assert record["analysis"]["phase"] == expected_phase
    assert "private" not in output.out + output.err


@pytest.mark.parametrize("status,exit_code", [("ready", 0), ("blocked", 1)])
def test_diagnostic_cli_reports_readiness_without_starting_polling(
    monkeypatch, capsys, status, exit_code
):
    import sys

    from cats_channel.cli import main

    diagnose = AsyncMock(return_value={"status": status, "publishing": "not_attempted"})
    monkeypatch.setattr("cats_channel.bot.preflight.diagnose_bot_api", diagnose)
    monkeypatch.setattr("cats_channel.cli.Settings", lambda: settings())
    monkeypatch.setattr(sys, "argv", ["cats-channel", "--bot-diagnose"])
    assert main() == exit_code
    assert json.loads(capsys.readouterr().out)["publishing"] == "not_attempted"
    diagnose.assert_awaited_once()


async def test_real_polling_listener_logs_failures_resets_and_preserves_backoff(
    monkeypatch, capsys
):
    bot = create_configured_bot(settings(), logger=configure_logging("INFO"))
    calls = []
    blocked = asyncio.Event()
    sleep = AsyncMock()
    monkeypatch.setattr(Backoff, "asleep", sleep)

    async def request(self, client, method, timeout=None):
        assert isinstance(method, GetUpdates)
        calls.append(method)
        if len(calls) <= 2:
            raise TelegramNetworkError(method=method, message="private-token-and-offset")
        if len(calls) == 3:
            return []  # A healthy empty long poll resets the failure series.
        if len(calls) == 4:
            raise TimeoutError("private-request-url")
        if len(calls) == 5:
            return [update("/start")]
        blocked.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(AiohttpSession, "make_request", request)
    listener = Dispatcher._listen_updates(bot)
    try:
        received = await asyncio.wait_for(anext(listener), 2)
        assert received.update_id == update("/start").update_id
        assert len(calls) == 5
        assert sleep.await_count == 3  # Aiogram, not the session, owns each delay.
        waiting = asyncio.create_task(anext(listener))
        await asyncio.wait_for(blocked.wait(), 2)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
    finally:
        await listener.aclose()
        await bot.session.close()

    output = capsys.readouterr().err
    records = [json.loads(line) for line in output.splitlines()]
    failures = [record for record in records if record["event"] == "bot_polling_failure"]
    assert [record["analysis"]["operation_attempts"] for record in failures] == [1, 2, 1]
    assert [record["analysis"]["automatic_retries"] for record in failures] == [0, 1, 0]
    assert all(record["code"] == "bot_api_network" for record in failures)
    assert all(record["analysis"]["phase"] == "bot_api_get_updates" for record in failures)
    assert all(record["operation"] == "bot_polling" for record in failures)
    assert "private-" not in output


async def test_publication_failure_is_not_polled_logged_or_retried(monkeypatch, capsys):
    bot = create_configured_bot(settings(), logger=configure_logging("INFO"))
    request = AsyncMock(side_effect=TimeoutError("private-media-send"))
    monkeypatch.setattr(AiohttpSession, "make_request", request)
    try:
        with pytest.raises(TelegramNetworkError):
            await bot(SendVideo(chat_id=42, video="private-file-id"))
    finally:
        await bot.session.close()

    assert request.await_count == 1
    assert capsys.readouterr().err == ""


async def test_polling_api_rejection_is_recorded_and_propagated(monkeypatch, capsys):
    bot = create_configured_bot(settings(), logger=configure_logging("INFO"))
    error = TelegramUnauthorizedError(method=GetUpdates(), message="private-api-body")
    request = AsyncMock(side_effect=error)
    monkeypatch.setattr(AiohttpSession, "make_request", request)
    try:
        with pytest.raises(TelegramUnauthorizedError) as caught:
            await bot.get_updates()
    finally:
        await bot.session.close()

    assert caught.value is error
    assert request.await_count == 1
    output = capsys.readouterr().err
    record = json.loads(output)
    assert record["analysis"]["phase"] == "bot_api_get_updates"
    assert record["analysis"]["operation_attempts"] == 1
    assert record["code"] == "internal_error"
    assert "private-api-body" not in output
