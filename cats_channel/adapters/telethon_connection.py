"""Telethon connection lifecycle and secret-safe error diagnosis middleware."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Self, TypeVar

from ..diagnostics import classify_exception, diagnostic_rule
from ..errors import MediaError, cleanup_warning_error
from .process import CancellationToken

T = TypeVar("T")


_TELETHON_EXCEPTION_RULES = (
    diagnostic_rule(
        "telegram_api_credentials",
        "configuration",
        "authentication",
        "high",
        r"^(?:ApiIdInvalid|ApiIdPublishedFlood|ConnectionApiIdInvalid)Error$",
    ),
    diagnostic_rule(
        "telegram_flood_wait",
        "remote_policy",
        "request",
        "high",
        r"(?:Flood|SlowModeWait)",
    ),
    diagnostic_rule(
        "telegram_phone",
        "authentication",
        "authentication",
        "high",
        r"^(?:PhoneNumber(?:AppSignupForbidden|Banned|Invalid|Unoccupied)|SendCodeUnavailable)Error$",
    ),
    diagnostic_rule(
        "telegram_login_code",
        "authentication",
        "authentication",
        "high",
        r"^(?:Code(?:Empty|HashInvalid|Invalid)|PhoneCode(?:Empty|Expired|HashEmpty|Invalid)|PhoneHashExpired)Error$",
    ),
    diagnostic_rule(
        "telegram_password",
        "authentication",
        "authentication",
        "high",
        r"^(?:Password(?:Empty|HashInvalid|Missing)|SessionPasswordNeeded|SrpPasswordChanged)Error$",
    ),
    diagnostic_rule(
        "timeout",
        "network",
        "request",
        "high",
        r"(?:Timeout|TimedOut)",
    ),
    diagnostic_rule(
        "telegram_login",
        "authentication",
        "session",
        "high",
        r"(?:AuthKey|AuthRestart|SecurityError|SessionRevoked|Unauthorized)",
    ),
    diagnostic_rule(
        "telegram_session_io",
        "local",
        "session",
        "medium",
        r"^(?:DatabaseError|DataError|IntegrityError|InterfaceError|OperationalError)$",
    ),
    diagnostic_rule(
        "telegram_connect",
        "network",
        "connection",
        "medium",
        r"(?:BrokenPipe|Connection|EOF|IncompleteRead|InvalidBuffer|Network|OSError|Proxy|Socket)",
    ),
    diagnostic_rule(
        "telegram_server",
        "remote",
        "request",
        "medium",
        r"(?:InterdcCall|RpcCallFail|ServerError|TimedOutError)",
    ),
)


def translate_telethon_error(error: Exception, *, phase: str) -> MediaError:
    code, analysis = classify_exception(
        error,
        _TELETHON_EXCEPTION_RULES,
        phase=phase,
        default_code="telegram_download",
        default_category="telegram",
    )
    return MediaError(code=code, log_analysis=analysis)


def _check_cancel(token: CancellationToken | None) -> None:
    if token is not None and token.cancelled:
        raise MediaError(code="cancelled")


async def cancellable(
    awaitable: Awaitable[T], token: CancellationToken | None, timeout: float
) -> T:
    """Bound and drain a Telethon operation while honoring thread cancellation."""
    task = asyncio.ensure_future(awaitable)
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while not task.done():
            _check_cancel(token)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise MediaError(code="timeout")
            await asyncio.wait({task}, timeout=min(0.1, remaining))
        _check_cancel(token)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class TelethonConnectionMiddleware:
    """Own one client lifecycle and classify every bounded operation by phase."""

    def __init__(
        self,
        client: Any,
        *,
        token: CancellationToken | None = None,
        connect_timeout: float = 30,
        disconnect_timeout: float = 15,
    ) -> None:
        self.client = client
        self.token = token
        self.connect_timeout = connect_timeout
        self.disconnect_timeout = disconnect_timeout
        self.connection_attempts = 0
        self.operation_attempts = 0
        self.completed_phases: list[str] = []
        self.failed_phase: str | None = None
        self._closed = False

    def _attach_counts(self, error: MediaError, phase: str) -> MediaError:
        if error.log_analysis is None:
            category = "control" if error.code == "cancelled" else "telegram"
            if error.code == "timeout":
                category = "network"
            error.log_analysis = {
                "primary": error.code,
                "category": category,
                "phase": phase,
                "confidence": "high",
                "signals": [error.code],
                "matched_line_scope": "exception",
                "exception_types": [type(error).__name__],
                "exception_chain_truncated": False,
                "raw_log_included": False,
            }
        error.log_analysis.update(
            connection_attempts=self.connection_attempts,
            operation_attempts=self.operation_attempts,
            automatic_retries=0,
        )
        return error

    def expected_error(self, code: str, *, phase: str) -> MediaError:
        self.failed_phase = phase
        return self._attach_counts(MediaError(code=code), phase)

    async def call(
        self,
        phase: str,
        awaitable: Awaitable[T],
        *,
        timeout: float | None,
    ) -> T:
        self.operation_attempts += 1
        try:
            if timeout is None:
                result = await awaitable
            else:
                result = await cancellable(awaitable, self.token, timeout)
        except MediaError as error:
            self.failed_phase = phase
            raise self._attach_counts(error, phase)
        except Exception as error:  # noqa: BLE001 - converted to stable safe taxonomy
            self.failed_phase = phase
            translated = translate_telethon_error(error, phase=phase)
            raise self._attach_counts(translated, phase) from None
        self.completed_phases.append(phase)
        return result

    async def __aenter__(self) -> Self:
        self.connection_attempts += 1
        try:
            await self.call("connection", self.client.connect(), timeout=self.connect_timeout)
        except BaseException as error:
            replacement = await self._finish(error)
            if replacement is not None:
                raise replacement from error
            raise
        return self

    async def __aexit__(self, _error_type, error: BaseException | None, _traceback) -> bool:
        replacement = await self._finish(error)
        if replacement is not None:
            raise replacement from error
        return False

    async def _finish(self, primary: BaseException | None) -> MediaError | None:
        if self._closed:
            return None
        self._closed = True
        try:
            await asyncio.wait_for(self.client.disconnect(), timeout=self.disconnect_timeout)
            self.completed_phases.append("disconnect")
        except Exception:  # noqa: BLE001 - raw client details must not escape
            self.failed_phase = "disconnect"
            if isinstance(primary, MediaError):
                primary.warnings += ("telegram_disconnect_failed",)
                return None
            if primary is not None:
                return cleanup_warning_error(primary, "telegram_disconnect_failed")
            return self.expected_error("cleanup_failed", phase="disconnect")
        return None

    def snapshot(self) -> dict[str, object]:
        return {
            "connection_attempts": self.connection_attempts,
            "operation_attempts": self.operation_attempts,
            "automatic_retries": 0,
            "completed_phases": list(self.completed_phases),
            "failed_phase": self.failed_phase,
        }
