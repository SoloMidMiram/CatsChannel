"""Bot-facing error adaptation and the final unexpected-error boundary."""

from __future__ import annotations

import asyncio
import logging

from aiogram.types import ErrorEvent, Message

from ..diagnostics import log_failure
from ..errors import MediaError, error_record
from .context import BotOperation


def diagnostic_error(error: BaseException, *, code: str, phase: str) -> MediaError:
    """Describe an exception safely without copying its message."""
    return MediaError(
        code=code,
        log_analysis={
            "phase": phase,
            "exception_types": [type(error).__name__],
            "raw_log_included": False,
        },
    )


async def answer_error_safely(
    message: Message,
    *,
    code: str,
    logger: logging.Logger,
    operation: BotOperation,
    event: str,
) -> bool:
    """Render one policy response without allowing notification failure to escape."""
    record = error_record(code)
    try:
        await message.answer(f"{record['message']}\n{record['action']}")
    except asyncio.CancelledError:
        raise
    except Exception as notification_error:  # noqa: BLE001 - final notification boundary
        operation.fail(code)
        log_failure(
            logger,
            event,
            diagnostic_error(
                notification_error,
                code="internal_error",
                phase="bot_error_notification",
            ),
            operation=operation.operation,
            correlation_id=operation.correlation_id,
        )
        return False
    return True


async def contain_unexpected_bot_error(
    event: ErrorEvent,
    logger: logging.Logger,
    bot_operation: BotOperation | None = None,
) -> bool:
    """Stop unexpected handler failures at a secret-safe router boundary."""
    error = event.exception
    if isinstance(error, asyncio.CancelledError):
        raise error
    operation = bot_operation or BotOperation(
        correlation_id="unavailable",
        operation="bot_update",
        started_at=0.0,
    )
    operation.fail("internal_error")
    diagnostic = diagnostic_error(error, code="internal_error", phase="bot_update")
    log_failure(
        logger,
        "bot_unexpected_failure",
        diagnostic,
        operation=operation.operation,
        correlation_id=operation.correlation_id,
    )
    message = event.update.message
    if message is not None:
        await answer_error_safely(
            message,
            code="internal_error",
            logger=logger,
            operation=operation,
            event="bot_error_notification_failure",
        )
    return True
