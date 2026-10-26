"""Read-only Bot API preflight with bounded calls and secret-safe output."""

import asyncio

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)

from ..async_cleanup import complete_cleanup
from ..config import Settings
from .transport import create_configured_bot


async def diagnose_bot_api(settings: Settings, *, bot: Bot | None = None) -> dict[str, object]:
    settings.require_bot()
    owned = bot is None
    client = bot if bot is not None else create_configured_bot(settings)
    report: dict[str, object] = {
        "status": "blocked",
        "scope": "read_only_bot_api",
        "proxy_configured": settings.bot_api_proxy is not None,
        "proxy_enabled": settings.bot_api_proxy_enabled,
        "proxy_in_use": settings.effective_bot_api_proxy is not None,
        "proxy_scheme": (
            settings.effective_bot_api_proxy.scheme if settings.effective_bot_api_proxy else None
        ),
        "reply_entries_enabled": settings.reply_entries_enabled,
        "get_me": "not_checked",
        "webhook": "not_checked",
        "destination": "not_checked",
        "publishing": "not_attempted",
        "phase": "get_me",
        "private_pilot_ready": False,
    }
    try:
        async with asyncio.timeout(settings.bot_api_timeout_seconds):
            me = await client.get_me()
            report["get_me"] = "ok"
            report["phase"] = "get_webhook_info"
            webhook = await client.get_webhook_info()
            report["webhook"] = "active" if webhook.url else "absent"
            report["polling_ready"] = not webhook.url
            # Report queue size, never webhook URL, certificate, IP, or error text.
            report["pending_updates"] = webhook.pending_update_count
            if not settings.channel_id:
                report["error_category"] = "destination_not_configured"
                return report
            try:
                destination = int(settings.channel_id)
            except ValueError:
                report["error_category"] = "numeric_destination_required"
                return report
            report["phase"] = "get_chat"
            chat = await client.get_chat(destination)
            report["phase"] = "get_chat_member"
            member = await client.get_chat_member(destination, me.id)
            report["destination"] = "accessible"
            report["destination_type"] = chat.type
            report["private_channel"] = chat.type == "channel" and not chat.username
            report["bot_membership"] = member.status
            report["can_post_messages"] = (
                getattr(member, "can_post_messages", False) is True or member.status == "creator"
            )
            report["can_edit_messages"] = (
                getattr(member, "can_edit_messages", False) is True or member.status == "creator"
            )
            ready = (
                not webhook.url
                and chat.type == "channel"
                and member.status in {"administrator", "creator"}
                and report["can_post_messages"]
                and settings.reply_entries_enabled
            )
            if settings.review_channel_id is not None:
                report["phase"] = "review_channel_permissions"
                review_chat = chat
                review_member = member
                if settings.review_channel_id != destination:
                    review_chat = await client.get_chat(settings.review_channel_id)
                    review_member = await client.get_chat_member(settings.review_channel_id, me.id)
                review_ready = review_chat.type == "channel" and (
                    review_member.status == "creator"
                    or (
                        review_member.status == "administrator"
                        and getattr(review_member, "can_post_messages", False) is True
                        and getattr(review_member, "can_edit_messages", False) is True
                    )
                )
                report["review_channel_ready"] = review_ready
                ready = ready and review_ready
            report["status"] = "ready" if ready else "blocked"
            report["private_pilot_ready"] = ready and report["private_channel"]
            report["phase"] = "complete"
            return report
    except asyncio.CancelledError:
        raise
    except (TelegramUnauthorizedError, TelegramForbiddenError) as error:
        report["error_category"] = (
            "bot_api_unauthorized"
            if isinstance(error, TelegramUnauthorizedError)
            else "bot_api_forbidden"
        )
    except (TimeoutError, TelegramNetworkError):
        report["error_category"] = "bot_api_network"
    except TelegramBadRequest:
        report["error_category"] = "bot_api_rejected"
    except Exception:  # noqa: BLE001 - no tokens, API URLs, payloads or exception text
        report["error_category"] = "bot_api_unavailable"
    finally:
        if owned:
            await complete_cleanup(client.session.close())
    return report
