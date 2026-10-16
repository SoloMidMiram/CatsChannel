"""Telethon connection lifecycle and secret-safe error diagnosis middleware."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Self, TypeVar

from ..diagnostics import classify_exception, diagnostic_rule
from ..errors import MediaError, cleanup_warning_error
from .process import CancellationToken

T = TypeVar("T")

_TASK_DRAIN_GRACE_SECONDS = 0.1
_OWNED_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


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


def _retrieve_task(task: asyncio.Task[Any]) -> None:
    """Retrieve a completed task result without exposing its exception text."""
    _OWNED_BACKGROUND_TASKS.discard(task)
    try:
        task.result()
    except BaseException:  # noqa: BLE001 - retrieval must include task cancellation
        return


def _own_pending_task(task: asyncio.Task[Any], owner: set[asyncio.Task[Any]] | None) -> None:
    """Keep a strong reference and always retrieve a late task result."""
    _OWNED_BACKGROUND_TASKS.add(task)
    if owner is not None:
        owner.add(task)

    def finished(completed: asyncio.Task[Any]) -> None:
        if owner is not None:
            owner.discard(completed)
        _retrieve_task(completed)

    task.add_done_callback(finished)


async def _cancel_and_drain(
    task: asyncio.Task[Any],
    timeout: float,
    owner: set[asyncio.Task[Any]] | None = None,
) -> bool:
    """Cancel once and wait for at most the cleanup grace budget."""
    if task.done():
        _retrieve_task(task)
        return True
    task.cancel()
    waiter = asyncio.create_task(asyncio.wait({task}, timeout=max(0.0, timeout)))
    # Repeated cancellation must not orphan the bounded drain waiter. Its own
    # timeout remains the upper bound, so this loop cannot extend the budget.
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            continue
    done, _pending = waiter.result()
    if task in done:
        _retrieve_task(task)
        return True
    _own_pending_task(task, owner)
    return False


async def cancellable(
    awaitable: Awaitable[T],
    token: CancellationToken | None,
    timeout: float,
    *,
    shutdown_timeout: float = _TASK_DRAIN_GRACE_SECONDS,
    owner: set[asyncio.Task[Any]] | None = None,
) -> T:
    """Bound a Telethon operation and give cancellation one finite drain budget."""
    task = asyncio.ensure_future(awaitable)
    primary: BaseException | None = None
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
    except BaseException as error:
        primary = error
        raise
    finally:
        if task.done():
            _retrieve_task(task)
        elif not await _cancel_and_drain(task, shutdown_timeout, owner) and isinstance(
            primary, MediaError
        ):
            primary.warnings += ("telegram_operation_cleanup_pending",)


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
        self.cleanup_failed_phase: str | None = None
        self.cleanup_pending = False
        self._owned_tasks: set[asyncio.Task[Any]] = set()
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
                result = await cancellable(
                    awaitable,
                    self.token,
                    timeout,
                    owner=self._owned_tasks,
                )
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
        direct_disconnect = getattr(self.client, "_disconnect_coro", None)
        awaitable = direct_disconnect() if callable(direct_disconnect) else self.client.disconnect()
        shielded_fallback = not callable(direct_disconnect) and isinstance(
            awaitable, asyncio.Future
        )
        disconnect_task = asyncio.ensure_future(awaitable)
        failure_warning = "telegram_disconnect_failed"
        try:
            try:
                done, _pending = await asyncio.wait(
                    {disconnect_task}, timeout=self.disconnect_timeout
                )
            except asyncio.CancelledError as cancellation:
                drained = await _cancel_and_drain(
                    disconnect_task,
                    _TASK_DRAIN_GRACE_SECONDS,
                    self._owned_tasks,
                )
                self.cleanup_pending = not drained or shielded_fallback
                self.cleanup_failed_phase = "disconnect"
                self._closed = disconnect_task.done() and not self.cleanup_pending
                warning = (
                    "telegram_cleanup_pending"
                    if self.cleanup_pending
                    else "telegram_disconnect_failed"
                )
                if isinstance(primary, MediaError):
                    primary.warnings += (warning,)
                    return None
                return cleanup_warning_error(primary or cancellation, warning)
            if disconnect_task not in done:
                drained = await _cancel_and_drain(
                    disconnect_task,
                    _TASK_DRAIN_GRACE_SECONDS,
                    self._owned_tasks,
                )
                # A Future returned by the public disconnect wrapper may be a
                # shield whose underlying task cannot be recovered. Telethon's
                # private coroutine above avoids that case; generic shielded
                # fallbacks retain the external session lock after timeout.
                self.cleanup_pending = not drained or shielded_fallback
                if self.cleanup_pending:
                    failure_warning = "telegram_cleanup_pending"
                raise TimeoutError
            disconnect_task.result()
            self.completed_phases.append("disconnect")
            if self._owned_tasks:
                self.cleanup_pending = True
                self.cleanup_failed_phase = "operation_cleanup"
                self._closed = False
                if isinstance(primary, MediaError):
                    if "telegram_cleanup_pending" not in primary.warnings:
                        primary.warnings += ("telegram_cleanup_pending",)
                    return None
                if primary is not None:
                    return cleanup_warning_error(primary, "telegram_cleanup_pending")
                error = self._attach_counts(MediaError(code="cleanup_failed"), "disconnect")
                error.warnings += ("telegram_cleanup_pending",)
                return error
            self._closed = True
        except Exception:  # noqa: BLE001 - raw client details must not escape
            self.cleanup_failed_phase = "disconnect"
            if self.failed_phase is None:
                self.failed_phase = "disconnect"
            self.cleanup_pending = self.cleanup_pending or bool(self._owned_tasks)
            self._closed = disconnect_task.done() and not self.cleanup_pending
            if isinstance(primary, MediaError):
                primary.warnings += (failure_warning,)
                return None
            if primary is not None:
                return cleanup_warning_error(primary, failure_warning)
            error = self._attach_counts(MediaError(code="cleanup_failed"), "disconnect")
            if failure_warning != "telegram_disconnect_failed":
                error.warnings += (failure_warning,)
            return error
        return None

    def snapshot(self) -> dict[str, object]:
        return {
            "connection_attempts": self.connection_attempts,
            "operation_attempts": self.operation_attempts,
            "automatic_retries": 0,
            "completed_phases": list(self.completed_phases),
            "failed_phase": self.failed_phase,
            "cleanup_failed_phase": self.cleanup_failed_phase,
            "cleanup_pending": self.cleanup_pending,
        }
