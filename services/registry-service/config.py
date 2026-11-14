from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings

ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    database_url: str
    db_connect_timeout_seconds: int = 3
    db_busy_timeout_seconds: float = 5
    db_pool_timeout_seconds: float = 5


def get_settings() -> Settings:
    try:
        return Settings(_env_file=ENV_FILE)
    except ValidationError as exc:
        if any(err["loc"] == ("database_url",) for err in exc.errors()):
            raise RuntimeError(
                "DATABASE_URL is required. Copy .env.example to .env and set it."
            ) from None
        raise
