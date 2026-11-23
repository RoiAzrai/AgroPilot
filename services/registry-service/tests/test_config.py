import pytest
from pydantic import ValidationError

import config

TIMEOUT_KEYS = (
    "DB_CONNECT_TIMEOUT_SECONDS",
    "DB_BUSY_TIMEOUT_SECONDS",
    "DB_POOL_TIMEOUT_SECONDS",
)


@pytest.mark.parametrize("key", TIMEOUT_KEYS)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_timeouts_must_be_above_zero(monkeypatch, tmp_path, key, value):
    # 0 means "wait forever" in PostgreSQL; a negative value fails every connect.
    monkeypatch.setenv("DATABASE_URL", "sqlite:///file:x.db?mode=rw&uri=true")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "none.env")
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError) as exc:
        config.get_settings()
    [error] = exc.value.errors()
    assert error["loc"] == (key.lower(),)
    assert error["type"] == "greater_than"


def test_reads_database_url_from_environment(monkeypatch, tmp_path):
    url = "sqlite:///file:x.db?mode=rw&uri=true"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "none.env")
    settings = config.get_settings()
    assert settings.database_url == url
    assert settings.db_connect_timeout_seconds == 3
    assert settings.db_busy_timeout_seconds == 5
    assert settings.db_pool_timeout_seconds == 5


def test_environment_wins_over_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite:///from-file\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from-env")
    assert config.get_settings().database_url == "sqlite:///from-env"


def test_env_file_is_read(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=sqlite:///from-file\nDB_BUSY_TIMEOUT_SECONDS=0.05\n"
    )
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_BUSY_TIMEOUT_SECONDS", raising=False)
    settings = config.get_settings()
    assert settings.database_url == "sqlite:///from-file"
    assert settings.db_busy_timeout_seconds == 0.05


def test_missing_database_url_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "none.env")
    with pytest.raises(RuntimeError, match="^DATABASE_URL is required"):
        config.get_settings()
