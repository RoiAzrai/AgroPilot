from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid", allow_inf_nan=False)

    registry_url: str
    weather_url: str
    registry_timeout_seconds: float = Field(3, gt=0)
    weather_timeout_seconds: float = Field(6, gt=0)
    max_daily_run_minutes: int = Field(1440, ge=1, le=1440)
    depletion_fraction_override: float | None = Field(None, ge=0, le=1)
    weather_refresh_deadline_seconds: float = Field(5, gt=0)
    retry_after_seconds: int = Field(5, ge=1)


def get_settings() -> Settings:
    try:
        settings = Settings(_env_file=ENV_FILE)
    except ValidationError as exc:
        problems = "; ".join(
            f"{str(err['loc'][0]).upper()}: "
            f"{'is required' if err['type'] == 'missing' else err['msg']}"
            for err in exc.errors()
            if err["loc"]
        )
        raise RuntimeError(
            f"Invalid settings. {problems}. Copy .env.example to .env and fix it."
        ) from None
    for key in ("registry_url", "weather_url"):
        value = getattr(settings, key)
        if not value.strip():
            raise RuntimeError(f"{key.upper()} is required and must not be empty.")
        if not value.startswith(("http://", "https://")):
            raise RuntimeError(f"{key.upper()} must start with http:// or https://.")
    if settings.weather_timeout_seconds <= settings.weather_refresh_deadline_seconds:
        raise RuntimeError(
            "WEATHER_TIMEOUT_SECONDS must be above WEATHER_REFRESH_DEADLINE_SECONDS."
        )
    return settings
