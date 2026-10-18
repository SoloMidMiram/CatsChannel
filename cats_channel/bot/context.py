"""Per-update operation context and secret-safe completion logging."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Message, TelegramObject

from ..diagnostics import log_operation


def operation_name(event: TelegramObject) -> str:
    """Derive an allowlisted operation name without retaining message text."""
    if not isinstance(event, Message):
        return "telegram_update"
    text = event.text or ""
    if not text.startswith("/"):
        return "message"
    command = text.split(maxsplit=1)[0].removeprefix("/").split("@", 1)[0].lower()
    return (
        command
        if command in {"start", "help", "post", "submit", "probe", "download", "publish", "cancel"}
        else "command"
    )


@dataclass
class BotOperation:
    """Mutable result metadata shared by middleware and the selected handler."""

    correlation_id: str
    operation: str
    started_at: float
    outcome: str = "success"
    error_category: str | None = None

    def fail(self, category: str, *, outcome: str = "error") -> None:
        self.outcome = outcome
        self.error_category = category


class BotOperationRegistry:
    """Bridge message middleware context to aiogram's outer error observer."""

    def __init__(self) -> None:
        self._operations: dict[int, BotOperation] = {}

    def register(self, event: TelegramObject, operation: BotOperation) -> None:
        self._operations[id(event)] = operation

    def take(self, event: TelegramObject | None) -> BotOperation | None:
        return None if event is None else self._operations.pop(id(event), None)

    def discard(self, event: TelegramObject) -> None:
        self._operations.pop(id(event), None)

    @property
    def pending_count(self) -> int:
        return len(self._operations)


class OperationLoggingMiddleware(BaseMiddleware):
    """Inject operation context and emit one bounded completion record."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        registry: BotOperationRegistry,
        clock: Callable[[], float] = time.monotonic,
        correlation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._logger = logger
        self._registry = registry
        self._clock = clock
        self._correlation_id_factory = correlation_id_factory or (lambda: secrets.token_hex(8))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started_at = self._clock()
        context = BotOperation(
            correlation_id=self._correlation_id_factory(),
            operation=operation_name(event),
            started_at=started_at,
        )
        data["bot_operation"] = context
        self._registry.register(event, context)
        preserve_for_error_boundary = False
        try:
            result = await handler(event, data)
            if result is UNHANDLED:
                context.outcome = "ignored"
            return result
        except asyncio.CancelledError:
            context.fail("cancelled", outcome="cancelled")
            raise
        except Exception:
            # Expected MediaError policies are handled in the command router.
            # Match the outer boundary without inspecting third-party attributes.
            context.fail("internal_error")
            preserve_for_error_boundary = True
            raise
        finally:
            duration_ms = max(0, round((self._clock() - started_at) * 1000))
            log_operation(
                self._logger,
                correlation_id=context.correlation_id,
                operation=context.operation,
                duration_ms=duration_ms,
                outcome=context.outcome,
                error_category=context.error_category,
            )
            if not preserve_for_error_boundary:
                self._registry.discard(event)
