from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parent / ".env"
MISSING_BASE_URL = "PROVIDER_BASE_URL is required. Copy .env.example to .env and set it."


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid", allow_inf_nan=False)

    provider_base_url: str
    provider_api_key: str = ""
    provider_attempt_timeout_seconds: float = Field(1.5, ge=0)
    provider_retries: int = Field(2, ge=0)
    provider_retry_backoff_seconds: float = Field(0.2, ge=0)
    refresh_deadline_seconds: float = Field(5, ge=0)
    forecast_fresh_seconds: float = Field(10800, ge=0)
    forecast_max_stale_seconds: float = Field(86400, ge=0)
    failure_pause_seconds: float = Field(60, ge=0)
    retry_after_seconds: int = Field(5, ge=0)


def get_settings() -> Settings:
    try:
        settings = Settings(_env_file=ENV_FILE)
    except ValidationError as exc:
        errors = exc.errors()
        if any(err["loc"] == ("provider_base_url",) and err["type"] == "missing" for err in errors):
            raise RuntimeError(MISSING_BASE_URL) from None
        problems = "; ".join(
            f"{str(err['loc'][0]).upper()}: {err['msg']}" for err in errors if err["loc"]
        )
        raise RuntimeError(f"Invalid settings. {problems}") from None
    if not settings.provider_base_url.strip():
        raise RuntimeError(MISSING_BASE_URL)
    if settings.provider_attempt_timeout_seconds >= settings.refresh_deadline_seconds:
        raise RuntimeError(
            "PROVIDER_ATTEMPT_TIMEOUT_SECONDS must be below REFRESH_DEADLINE_SECONDS."
        )
    if settings.forecast_fresh_seconds > settings.forecast_max_stale_seconds:
        raise RuntimeError(
            "FORECAST_FRESH_SECONDS must not exceed FORECAST_MAX_STALE_SECONDS."
        )
    return settings
