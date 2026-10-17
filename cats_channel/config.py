from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, AnyUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import MediaError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    bot_token: SecretStr = SecretStr("")
    admin_user_id: int | None = None
    channel_id: str | None = None
    youtube_cookie_file: Path | None = None
    youtube_profile: Literal["baseline", "pot_bgutil"] = "baseline"
    youtube_pot_provider_url: AnyHttpUrl | None = None
    youtube_proxy: AnyUrl | None = None
    download_dir: Path = Path("downloads")
    max_download_mb: int = Field(default=45, ge=1, le=45)
    max_duration_seconds: int = Field(default=300, ge=1, le=1800)
    media_backend: Literal["yt_dlp", "telegram_bot"] = "yt_dlp"
    telegram_api_id: int | None = Field(default=None, ge=1, repr=False)
    telegram_api_hash: SecretStr = SecretStr("")
    telethon_session: Path = Path(".secrets/user")
    telegram_proxy: AnyUrl | None = None
    telegram_downloader_bot: str = "whatsmusicbot"
    telegram_response_timeout: int = Field(default=180, ge=10, le=600)
    database_url: SecretStr = SecretStr("sqlite+aiosqlite:///cats_channel.sqlite3")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"

    @property
    def telegram_session_file(self) -> Path:
        value = str(self.telethon_session)
        return Path(value if value.endswith(".session") else f"{value}.session")

    @field_validator("telegram_downloader_bot")
    @classmethod
    def validate_downloader_bot(cls, value: str) -> str:
        import re

        username = value.removeprefix("@").lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{4,31}", username):
            raise ValueError("Expected a Telegram bot username")
        return username

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value().strip()
        parsed = urlsplit(url)
        if parsed.scheme not in {"sqlite+aiosqlite", "postgresql+asyncpg"}:
            raise ValueError("DATABASE_URL must use sqlite+aiosqlite or postgresql+asyncpg")
        if parsed.fragment:
            raise ValueError("DATABASE_URL must not contain a fragment")
        if parsed.scheme == "sqlite+aiosqlite" and (parsed.netloc or parsed.path in {"", "/"}):
            raise ValueError("DATABASE_URL must identify a database")
        if parsed.scheme == "postgresql+asyncpg" and (
            parsed.hostname is None or parsed.path in {"", "/"}
        ):
            raise ValueError("DATABASE_URL must include a host and database name")
        return SecretStr(url)

    def require_telegram_client(self) -> None:
        if not self.telegram_api_id or not self.telegram_api_hash.get_secret_value():
            raise MediaError(code="telegram_config")

    @field_validator("telegram_proxy")
    @classmethod
    def validate_telegram_proxy(cls, value: AnyUrl | None) -> AnyUrl | None:
        if value is None:
            return None
        if value.scheme not in {"http", "socks4", "socks4a", "socks5", "socks5h"}:
            raise ValueError("TELEGRAM_PROXY must use HTTP or SOCKS")
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in {None, "", "/"}
        ):
            raise ValueError("TELEGRAM_PROXY must be an origin without credentials")
        if value.host is None or value.port is None:
            raise ValueError("TELEGRAM_PROXY must include a host and port")
        return value

    @field_validator("youtube_pot_provider_url")
    @classmethod
    def validate_pot_provider_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and (
            value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in {None, "", "/"}
        ):
            raise ValueError("YOUTUBE_POT_PROVIDER_URL must be an origin without credentials")
        return value

    @field_validator("youtube_proxy")
    @classmethod
    def validate_youtube_proxy(cls, value: AnyUrl | None) -> AnyUrl | None:
        if value is None:
            return None
        if value.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}:
            raise ValueError("YOUTUBE_PROXY must use HTTP(S) or SOCKS")
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in {None, "", "/"}
        ):
            raise ValueError("YOUTUBE_PROXY must be an origin without credentials")
        if value.host is None or value.port is None:
            raise ValueError("YOUTUBE_PROXY must include a host and port")
        return value

    def require_bot(self) -> None:
        if not self.bot_token.get_secret_value() or not self.admin_user_id:
            raise MediaError(code="invalid_config")
