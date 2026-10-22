"""Temporary explicit admin approval. Issue #8 replaces this narrow policy."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ...publication.errors import PublicationError
from ...publication.service import PublicationService
from ..context import BotOperation


def create_pilot_router() -> Router:
    # Included only under the existing private/admin-filtered router.
    router = Router(name="publication_pilot")

    @router.message(Command("pilot_publish"))
    async def pilot_publish(
        message: Message,
        bot_operation: BotOperation,
        publication_service: PublicationService | None = None,
    ):
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer(
                "Usage: /pilot_publish <submission-id>. This explicitly approves that pending submission."
            )
            bot_operation.outcome = "invalid_request"
            return
        if publication_service is None:
            raise PublicationError("publication_unavailable")
        result = await publication_service.approve_pilot(parts[1])
        bot_operation.outcome = result.state
        bot_operation.publication_state = result.state
        if result.error_category is not None:
            bot_operation.error_category = result.error_category
        state = (
            "pending (owned sending attempt; do not retry)"
            if result.state == "sending"
            else result.state
        )
        markup = f"; reply button: {result.markup_status}" if result.state == "confirmed" else ""
        recovery = "; operator reconciliation required" if result.state == "unknown" else ""
        await message.answer(
            f"Pilot approval recorded: {state}{markup}{recovery}. Publication: {result.id}"
        )

    return router
