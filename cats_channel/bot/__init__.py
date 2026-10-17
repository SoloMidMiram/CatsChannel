"""Aiogram application composition and compatibility exports."""

from .application import BotApplication, create_bot_application, run_bot
from .entry import (
    ModerationCallback,
    ReplyTarget,
    ReplyTargetResolver,
    build_reply_link,
    new_reply_token,
    parse_reply_payload,
)
from .errors import contain_unexpected_bot_error
from .handlers import send_acquired_video

__all__ = [
    "BotApplication",
    "ModerationCallback",
    "ReplyTarget",
    "ReplyTargetResolver",
    "build_reply_link",
    "contain_unexpected_bot_error",
    "create_bot_application",
    "new_reply_token",
    "parse_reply_payload",
    "run_bot",
    "send_acquired_video",
]
