from pathlib import Path
from typing import Literal

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
