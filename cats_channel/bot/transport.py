"""One explicit Bot API session owner for polling, files, publication and recovery."""

import logging
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.methods.base import TelegramType
from aiohttp_socks import ProxyConnectionError, ProxyError, ProxyTimeoutError

from ..config import Settings
from ..diagnostics import log_failure
from .errors import bot_api_diagnostic_error


class BotApiSession(AiohttpSession):
    def __init__(self, *args: Any, logger: logging.Logger | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._logger = logger or logging.getLogger("cats_channel")
        self._get_updates_failures = 0

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        try:
            try:
                result = await super().make_request(bot, method, timeout)
            except (
                ProxyConnectionError,
                ProxyError,
                ProxyTimeoutError,
                TelegramNetworkError,
                TimeoutError,
            ):
                # Normalize only failures of this known Bot API request.
                raise TelegramNetworkError(
                    method=method, message="Bot API connection failed"
                ) from None
        except Exception as error:
            if isinstance(method, GetUpdates):
                self._get_updates_failures += 1
                log_failure(
                    self._logger,
                    "bot_polling_failure",
                    bot_api_diagnostic_error(
                        error,
                        fallback_phase="bot_api_get_updates",
                        operation_attempts=self._get_updates_failures,
                    ),
                    operation="bot_polling",
                )
            # Aiogram owns polling backoff; this session never retries a request.
            raise
        if isinstance(method, GetUpdates):
            self._get_updates_failures = 0
        return result


def create_configured_bot(settings: Settings, *, logger: logging.Logger | None = None) -> Bot:
    """No implicit environment-proxy fallback or media retry policy."""
    # Validate before allocating a session. Existing tests may inject their own Bot.
    token = settings.bot_token.get_secret_value()
    from aiogram.utils.token import validate_token

    validate_token(token)
    route = settings.effective_bot_api_proxy
    proxy = str(route) if route else None
    if proxy:
        # aiohttp-socks accepts base SOCKS schemes. aiogram explicitly uses rdns=True,
        # preserving remote DNS for the h/a aliases without a direct DNS fallback.
        scheme, address = proxy.split("://", 1)
        scheme = {"socks5h": "socks5", "socks4a": "socks4"}.get(scheme, scheme)
        proxy = f"{scheme}://{address}"
    session = BotApiSession(proxy=proxy, timeout=settings.bot_api_timeout_seconds, logger=logger)
    return Bot(token, session=session)
