"""Fail-closed, read-only review/publication startup policy."""

import asyncio

from ..errors import MediaError


def review_destinations(settings):
    # Legacy nonpersistent admin media utilities do not enable the product review flow.
    if not settings.reply_entries_enabled and settings.review_channel_id is None:
        return None
    try:
        destination = int(settings.channel_id)
    except (TypeError, ValueError):
        raise MediaError(code="review_configuration") from None
    review = settings.review_channel_id
    if (
        destination >= 0
        or type(review) is not int
        or review >= 0
        or type(settings.admin_user_id) is not int
        or settings.admin_user_id <= 0
        or (review == destination and settings.review_isolation_mode != "private_pilot")
    ):
        raise MediaError(code="review_configuration")
    return review, destination


async def verify_review_isolation(settings, bot):
    targets = review_destinations(settings)
    if targets is None:
        return
    review, destination = targets
    try:
        async with asyncio.timeout(settings.bot_api_timeout_seconds):
            me = await bot.me()
            for target in dict.fromkeys((review, destination)):
                chat = await bot.get_chat(target)
                member = await bot.get_chat_member(target, me.id)
                must_be_private = (
                    target == review or settings.review_isolation_mode == "private_pilot"
                )
                require_review_channel(chat, member, target, private=must_be_private)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - fail closed without exposing transport details
        # Do not disclose raw Bot API exceptions, IDs, URLs or credentials.
        raise MediaError(code="review_permissions_unverified") from None


def require_review_channel(chat, member, target, *, private):
    if chat.id != target or chat.type != "channel":
        raise MediaError(code="review_permissions_unverified")
    if private and (chat.username or getattr(chat, "active_usernames", None)):
        raise MediaError(code="review_permissions_unverified")
    if member.status != "creator" and not (
        member.status == "administrator"
        and getattr(member, "can_post_messages", False) is True
        and getattr(member, "can_edit_messages", False) is True
    ):
        raise MediaError(code="review_permissions_unverified")
