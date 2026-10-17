"""Await owned cleanup despite repeated caller cancellation."""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


async def finish_owned(task: asyncio.Task[T]) -> T:
    """Drain an owned task; record cancellation without cancelling that task."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:  # noqa: BLE001 - retrieve and re-raise the owned failure below
            break  # Retrieve the task's actual failure below.
    try:
        result = task.result()
    except Exception as error:
        if cancelled:
            raise asyncio.CancelledError from error
        raise
    if cancelled:
        raise asyncio.CancelledError
    return result


async def complete_cleanup(cleanup: Awaitable[T]) -> T:
    return await finish_owned(asyncio.create_task(cleanup))
