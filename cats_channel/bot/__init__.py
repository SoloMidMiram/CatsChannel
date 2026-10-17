"""Aiogram application composition and compatibility exports."""

from .application import BotApplication, create_bot_application, run_bot
from .errors import contain_unexpected_bot_error
from .handlers import send_acquired_video

__all__ = [
    "BotApplication",
    "contain_unexpected_bot_error",
    "create_bot_application",
    "run_bot",
    "send_acquired_video",
]
