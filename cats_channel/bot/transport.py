"""One explicit Bot API session owner for polling, files, publication and recovery."""

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiohttp_socks import ProxyConnectionError, ProxyError, ProxyTimeoutError

from ..config import Settings


class BotApiSession(AiohttpSession):
    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        try:
            return await super().make_request(bot, method, timeout)
        except (ProxyConnectionError, ProxyError, ProxyTimeoutError, TelegramNetworkError):
            # aiohttp-socks errors are not aiohttp.ClientError subclasses. Keep one
            # safe transport boundary; do not retry or expose token-bearing URLs.
            raise TelegramNetworkError(method=method, message="Bot API connection failed") from None


def create_configured_bot(settings: Settings) -> Bot:
    """No implicit environment-proxy fallback or media retry policy."""
    # Validate before allocating a session. Existing tests may inject their own Bot.
    token = settings.bot_token.get_secret_value()
    from aiogram.utils.token import validate_token

    validate_token(token)
    proxy = str(settings.bot_api_proxy) if settings.bot_api_proxy else None
    if proxy:
        # aiohttp-socks accepts base SOCKS schemes. aiogram explicitly uses rdns=True,
        # preserving remote DNS for the h/a aliases without a direct DNS fallback.
        scheme, address = proxy.split("://", 1)
        scheme = {"socks5h": "socks5", "socks4a": "socks4"}.get(scheme, scheme)
        proxy = f"{scheme}://{address}"
    session = BotApiSession(proxy=proxy, timeout=settings.bot_api_timeout_seconds)
    return Bot(token, session=session)
