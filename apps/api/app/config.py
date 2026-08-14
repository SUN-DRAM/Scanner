"""Application settings, read from environment variables (contract §4)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- shared ---
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # --- api ---
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    database_url: str = Field(
        default="postgresql+psycopg://scanner:scanner@postgres:5432/scanner",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    scan_timeout_seconds: int = Field(default=25, alias="SCAN_TIMEOUT_SECONDS")
    scan_cache_ttl_seconds: int = Field(default=900, alias="SCAN_CACHE_TTL_SECONDS")
    rate_limit_per_ip_per_hour: int = Field(default=20, alias="RATE_LIMIT_PER_IP_PER_HOUR")
    rate_limit_per_hostname_per_hour: int = Field(
        default=6, alias="RATE_LIMIT_PER_HOSTNAME_PER_HOUR"
    )
    public_base_url: str = Field(default="http://localhost:3000", alias="PUBLIC_BASE_URL")
    # Empty by default: no default token means /api/v1/admin/stats refuses
    # every request until this is explicitly set, rather than shipping a
    # guessable default that "works" out of the box.
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")
    # Gate C. Empty by default: no DSN means Sentry is never initialised —
    # error tracking is opt-in, never a silent default data destination.
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    # Phase 2 §7.6. Signs the sd_session cookie. No default — an empty
    # secret would make every session forgeable, so app.sessions refuses to
    # start signing with it (see app/sessions.py) rather than silently
    # falling back to something guessable.
    session_secret: str = Field(default="", alias="SESSION_SECRET")
    # Phase 2 Step 2, CONTRACT GAP: not named by CONTRACT.md v2.0 — the
    # phase prompt's Step 1 didn't anticipate that OTP delivery (Step 2)
    # needs a real email provider before Step 5's own app/notify/email.py
    # is built. Added here out of necessity, same treatment SESSION_SECRET
    # already got: flagged, not silently invented. Empty by default —
    # app.notify.email falls back to logging the email instead of sending
    # it, the same "empty = opt-in" pattern as SENTRY_DSN/ADMIN_TOKEN.
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    email_from_address: str = Field(default="", alias="EMAIL_FROM_ADDRESS")

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CORS_ORIGINS must not be empty")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
