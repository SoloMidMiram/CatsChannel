"""Optional user-account transport for a bot that returns video directly.

Only an explicit login/download command connects or sends anything. The bot's
returned video is untrusted input; publication/validation belongs to library.py.
"""

import asyncio
import os
import shutil
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..config import Settings
from ..errors import MediaError, cleanup_warning_error, error_record
from ..media import youtube_url
from .process import CancellationToken
from .telethon_connection import (
    TelethonConnectionMiddleware,
    _check_cancel,
    cancellable,
)
from .telethon_connection import translate_telethon_error as _translate_error


async def _cancellable(awaitable, token: CancellationToken | None, timeout: float):
    """Compatibility facade for the tested cancellation primitive."""
    return await cancellable(awaitable, token, timeout)


def _session_file(settings: Settings) -> Path:
    return settings.telegram_session_file


def _telethon_proxy(settings: Settings) -> dict | None:
    """Translate the explicit URL setting to Telethon's proxy representation."""
    proxy = settings.telegram_proxy
    if proxy is None:
        return None
    scheme = proxy.scheme
    return {
        "proxy_type": {"socks5h": "socks5", "socks4a": "socks4"}.get(scheme, scheme),
        "addr": proxy.host,
        "port": proxy.port,
        "rdns": scheme in {"socks4a", "socks5h"},
    }


@contextmanager
def _session_lock(settings: Settings):
    session = _session_file(settings)
    session.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = Path(f"{session}.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise MediaError(code="telegram_busy") from None
    primary: BaseException | None = None
    try:
        os.close(descriptor)
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            lock.unlink()
        except OSError:
            if isinstance(primary, MediaError):
                primary.warnings += ("session_lock_cleanup_failed",)
            elif primary is not None:
                raise cleanup_warning_error(primary, "session_lock_cleanup_failed") from primary
            elif primary is None:
                raise MediaError(
                    code="cleanup_failed", warnings=("session_lock_cleanup_failed",)
                ) from None


def _make_client(settings: Settings):
    settings.require_telegram_client()
    try:
        from telethon import TelegramClient
    except ImportError:
        raise MediaError(code="telegram_config") from None
    return TelegramClient(
        str(_session_file(settings)),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
        proxy=_telethon_proxy(settings),
        request_retries=0,
        connection_retries=0,
        auto_reconnect=False,
        flood_sleep_threshold=0,
        raise_last_call_error=True,
        timeout=15,
    )


async def _receive_video(
    transport: TelethonConnectionMiddleware,
    settings: Settings,
    canonical: str,
    directory: Path,
    token: CancellationToken | None,
) -> tuple[Path, dict]:
    client = transport.client
    me = await transport.call("account", client.get_me(), timeout=30)
    if me is None or getattr(me, "bot", False):
        raise transport.expected_error("telegram_login", phase="account")
    peer = await transport.call(
        "bot_resolution", client.get_entity(settings.telegram_downloader_bot), timeout=30
    )
    if not getattr(peer, "bot", False):
        raise transport.expected_error("telegram_bot_flow", phase="bot_resolution")
    # One session operation at a time; never select an old message from history.
    async with client.conversation(
        peer,
        timeout=settings.telegram_response_timeout,
        total_timeout=settings.telegram_response_timeout,
        max_messages=30,
        exclusive=True,
    ) as conversation:
        _check_cancel(token)
        sent = await transport.call("request", conversation.send_message(canonical), timeout=30)
        deadline = asyncio.get_running_loop().time() + settings.telegram_response_timeout
        for _ in range(20):
            response = await transport.call(
                "response",
                conversation.get_response(),
                timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
            )
            if (
                getattr(response, "out", False)
                or response.sender_id != peer.id
                or response.id <= sent.id
            ):
                continue
            reply_id = getattr(response, "reply_to_msg_id", None)
            if reply_id is not None and reply_id != sent.id:
                continue
            document = getattr(response, "document", None)
            if document is not None:
                mime = getattr(document, "mime_type", "") or ""
                if not mime.startswith("video/"):
                    raise transport.expected_error("telegram_bot_flow", phase="response")
                size = getattr(document, "size", None)
                limit = settings.max_download_mb * 1024 * 1024
                if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= limit:
                    raise transport.expected_error("upload_limit", phase="response")
                extension = getattr(getattr(response, "file", None), "ext", None)
                if extension not in {".mp4", ".webm", ".mkv", ".mov"}:
                    raise transport.expected_error("format_unavailable", phase="response")
                target = directory / f"video{extension}"

                async def progress(current, _total, _limit=limit):
                    _check_cancel(token)
                    if current > _limit:
                        raise MediaError(code="upload_limit")

                await transport.call(
                    "transfer",
                    client.download_media(response, file=str(target), progress_callback=progress),
                    timeout=300,
                )
                if not target.is_file() or not 0 < target.stat().st_size <= limit:
                    raise transport.expected_error("download_output", phase="transfer")
                if target.stat().st_size != size:
                    raise transport.expected_error("media_validation", phase="transfer")
                return target, {
                    "backend": "telegram_bot",
                    "bot_username": settings.telegram_downloader_bot,
                    "bot_id": peer.id,
                    "request_message_id": sent.id,
                    "response_message_id": response.id,
                    "source_identity_verified": False,
                    "correlation": "reply" if reply_id == sent.id else "serialized_conversation",
                }
            if getattr(response, "buttons", None):
                raise transport.expected_error("telegram_bot_flow", phase="response")
        raise transport.expected_error("telegram_bot_flow", phase="response")


async def _download(
    settings: Settings, canonical: str, directory: Path, token: CancellationToken | None
) -> tuple[Path, dict]:
    if not _session_file(settings).is_file():
        raise MediaError(code="telegram_login")
    client = _make_client(settings)
    transport = TelethonConnectionMiddleware(client, token=token)
    async with transport:
        if not await transport.call("authorization", client.is_user_authorized(), timeout=30):
            raise transport.expected_error("telegram_login", phase="authorization")
        return await transport.call(
            "conversation",
            _receive_video(transport, settings, canonical, directory, token),
            timeout=None,
        )


def download_video(
    settings: Settings,
    url: str,
    directory: Path,
    *,
    metadata_out: dict,
    token: CancellationToken | None = None,
) -> Path:
    canonical = youtube_url(url)
    settings.require_telegram_client()
    _check_cancel(token)
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise MediaError(code="media_validation")
    with _session_lock(settings):
        path, receipt = asyncio.run(_download(settings, canonical, directory, token))
    video_id = parse_qs(urlsplit(canonical).query)["v"][0]
    metadata_out.update(
        {
            "id": video_id,
            "title": f"YouTube {video_id} via @{settings.telegram_downloader_bot}",
            "duration": None,  # Filled from local FFprobe, never invented from the request.
            "webpage_url": canonical,
            "_telegram_receipt": receipt,
        }
    )
    return path


async def login(settings: Settings) -> dict:
    """Interactive, local-only entry point. Download operations never prompt for login."""
    settings.require_telegram_client()
    with _session_lock(settings):
        client = _make_client(settings)
        transport = TelethonConnectionMiddleware(client)
        async with transport:
            await transport.call("login", client.start(), timeout=None)
            me = await transport.call("account", client.get_me(), timeout=30)
            if me is None or getattr(me, "bot", False):
                raise transport.expected_error("telegram_login", phase="account")
            return {"status": "ok", "message": "Telegram user session is ready."}


async def diagnose_connection(settings: Settings) -> dict[str, object]:
    """Make one read-only connection/auth check without prompting or sending messages."""
    started = time.monotonic()
    report: dict[str, object] = {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "operation": "telegram_connection",
        "session_file_present": False,
        "proxy_configured": settings.telegram_proxy is not None,
        "proxy_scheme": settings.telegram_proxy.scheme if settings.telegram_proxy else None,
        "connection_attempts": 0,
        "operation_attempts": 0,
        "automatic_retries": 0,
        "completed_phases": [],
        "failed_phase": None,
    }
    transport: TelethonConnectionMiddleware | None = None
    try:
        settings.require_telegram_client()
        report["session_file_present"] = _session_file(settings).is_file()
        if not report["session_file_present"]:
            raise MediaError(code="telegram_login")
        with _session_lock(settings):
            client = _make_client(settings)
            transport = TelethonConnectionMiddleware(client)
            async with transport:
                authorized = await transport.call(
                    "authorization", client.is_user_authorized(), timeout=30
                )
                if not authorized:
                    raise transport.expected_error("telegram_login", phase="authorization")
        report.update(status="ok", connection="passed", authorization="passed")
    except MediaError as error:
        report.update(status="error", error=error_record(error.code, str(error)))
        if error.log_analysis is not None:
            report["log_analysis"] = error.log_analysis
    except OSError as error:
        safe = MediaError(
            code="local_io",
            log_analysis={
                "primary": "local_io",
                "category": "local",
                "phase": "session",
                "confidence": "high",
                "signals": ["local_io"],
                "exception_types": [type(error).__name__],
                "raw_log_included": False,
            },
        )
        report.update(status="error", error=error_record(safe.code, str(safe)))
        report["log_analysis"] = safe.log_analysis
    except Exception as error:  # noqa: BLE001 - final diagnostic safety boundary
        safe = _translate_error(error, phase="diagnosis")
        report.update(status="error", error=error_record(safe.code, str(safe)))
        report["log_analysis"] = safe.log_analysis
    if transport is not None:
        report.update(transport.snapshot())
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return report
