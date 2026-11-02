"""Review callbacks may originate in a channel; private intake filters do not apply."""

from aiogram import Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery

from ...diagnostics import log_failure
from ...review.entities import ReviewError
from ..context import BotOperation
from ..errors import diagnostic_error


class ReviewApproval(CallbackData, prefix="reviewapprove"):
    review_id: str
    version: int


class ReviewRejection(CallbackData, prefix="reviewreject"):
    review_id: str
    version: int


def create_review_router(service):
    router = Router(name="review_approval")

    @router.callback_query(ReviewApproval.filter())
    @router.callback_query(ReviewRejection.filter())
    async def approve(
        query: CallbackQuery,
        callback_data: ReviewApproval | ReviewRejection,
        bot_operation: BotOperation,
        logger,
    ):
        rejecting = isinstance(callback_data, ReviewRejection)
        bot_operation.operation = "review_reject" if rejecting else "review_approve"
        if query.message is None:
            return
        try:
            decide = service.reject if rejecting else service.approve
            result = await decide(
                callback_data.review_id,
                callback_data.version,
                actor_id=query.from_user.id,
                chat_id=query.message.chat.id,
                message_id=query.message.message_id,
            )
            bot_operation.outcome = result.decision_state
            messages = {
                "approved": "Approved and published.",
                "approving": "Approval is already in progress.",
                "blocked": "Approval recorded; publication is blocked.",
                "needs_reconciliation": "Delivery needs reconciliation. Nothing was resent.",
                "rejected": "Rejected. Nothing was published.",
            }
            text = messages.get(result.decision_state, "Review is pending.")
            if result.decision_state in {"approved", "rejected"}:
                try:
                    await query.bot.edit_message_caption(
                        chat_id=result.review_chat_id,
                        message_id=result.message_id,
                        caption=(
                            "Rejected: " + result.rejection_reason + ". Nothing was published."
                            if result.decision_state == "rejected"
                            else "Approved. Published to the channel."
                        ),
                        reply_markup=None,
                    )
                except Exception as error:  # noqa: BLE001 - markup never changes confirmed media
                    log_failure(
                        logger,
                        "review_markup_failure",
                        diagnostic_error(error, code="review_markup_failed", phase="review_markup"),
                        operation=bot_operation.operation,
                    )
        except (ReviewError, ValueError) as error:
            bot_operation.fail(getattr(error, "code", "review_unavailable"))
            text = (
                "Only the configured admin can decide."
                if getattr(error, "code", "") == "review_forbidden"
                else "This review button is unavailable or stale."
            )
        except Exception as error:  # noqa: BLE001 - final secret-safe callback boundary
            bot_operation.fail("review_unavailable")
            log_failure(
                logger,
                "review_approval_failure",
                diagnostic_error(error, code="review_unavailable", phase="review_approve"),
                operation=bot_operation.operation,
            )
            text = "Review unavailable. The submission is saved; do not resend it."
        try:
            await query.answer(text)
        except Exception as error:  # noqa: BLE001 - notification cannot replay approval
            log_failure(
                logger,
                "review_callback_notification_failure",
                diagnostic_error(error, code="review_notification_failed", phase="review_callback"),
                operation=bot_operation.operation,
            )

    return router
