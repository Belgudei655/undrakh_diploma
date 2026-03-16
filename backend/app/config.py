from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./app.db"
    device_secret_pepper: str
    admin_username: str
    admin_password: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60
    heartbeat_poll_interval_ms: int = 5000
    command_poll_interval_ms: int = 1000
    command_poll_idle_interval_ms: int = 3000
    device_offline_timeout_seconds: int = 60
    sse_snapshot_interval_seconds: int = 5
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
