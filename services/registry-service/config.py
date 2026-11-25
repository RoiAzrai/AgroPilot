from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings

ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    database_url: str
    # gt=0: 0 means "wait forever" in PostgreSQL, and a negative value fails every connect.
    db_connect_timeout_seconds: int = Field(3, gt=0)
    db_busy_timeout_seconds: float = Field(5, gt=0)
    db_pool_timeout_seconds: float = Field(5, gt=0)
    # Plot photos. Credentials are never configured here: boto3 finds them itself
    # (~/.aws locally, the instance's IAM role on EC2).
    aws_s3_bucket: str
    aws_region: str
    s3_connect_timeout_seconds: float = Field(3, gt=0)
    s3_read_timeout_seconds: float = Field(10, gt=0)
    s3_max_attempts: int = Field(3, gt=0)


def get_settings() -> Settings:
    try:
        return Settings(_env_file=ENV_FILE)
    except ValidationError as exc:
        if any(err["loc"] == ("database_url",) for err in exc.errors()):
            raise RuntimeError(
                "DATABASE_URL is required. Copy .env.example to .env and set it."
            ) from None
        raise
