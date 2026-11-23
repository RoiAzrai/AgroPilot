import pytest

import config
from config import get_settings

NUMERIC_KEYS = [
    "PROVIDER_ATTEMPT_TIMEOUT_SECONDS",
    "PROVIDER_RETRIES",
    "PROVIDER_RETRY_BACKOFF_SECONDS",
    "REFRESH_DEADLINE_SECONDS",
    "FORECAST_FRESH_SECONDS",
    "FORECAST_MAX_STALE_SECONDS",
    "FAILURE_PAUSE_SECONDS",
    "RETRY_AFTER_SECONDS",
]


def test_defaults():
    s = get_settings()
    assert s.provider_base_url == "http://provider.invalid/v1/forecast"
    assert s.provider_api_key == ""
    assert s.provider_attempt_timeout_seconds == 1.5
    assert s.provider_retries == 2
    assert s.provider_retry_backoff_seconds == 0.2
    assert s.refresh_deadline_seconds == 5
    assert s.forecast_fresh_seconds == 10800
    assert s.forecast_max_stale_seconds == 86400
    assert s.failure_pause_seconds == 60
    assert s.retry_after_seconds == 5


def test_missing_base_url_is_clear(monkeypatch):
    monkeypatch.delenv("PROVIDER_BASE_URL")
    with pytest.raises(RuntimeError, match=r"^PROVIDER_BASE_URL is required"):
        get_settings()


def test_attempt_timeout_must_be_below_deadline(monkeypatch):
    monkeypatch.setenv("PROVIDER_ATTEMPT_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("REFRESH_DEADLINE_SECONDS", "5")
    with pytest.raises(RuntimeError) as exc:
        get_settings()
    assert "PROVIDER_ATTEMPT_TIMEOUT_SECONDS" in str(exc.value)
    assert "REFRESH_DEADLINE_SECONDS" in str(exc.value)
    monkeypatch.setenv("PROVIDER_ATTEMPT_TIMEOUT_SECONDS", "1.5")
    assert get_settings().provider_attempt_timeout_seconds == 1.5


@pytest.mark.parametrize("key", NUMERIC_KEYS)
def test_negative_values_rejected(monkeypatch, key):
    monkeypatch.setenv(key, "-1")
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize(
    "key",
    ["PROVIDER_ATTEMPT_TIMEOUT_SECONDS", "REFRESH_DEADLINE_SECONDS", "FORECAST_FRESH_SECONDS"],
)
@pytest.mark.parametrize("value", ["0", "-0.5"])
def test_must_be_above_zero(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize("value", ["0", "-1"])
def test_retry_after_must_be_at_least_one(monkeypatch, value):
    monkeypatch.setenv("RETRY_AFTER_SECONDS", value)
    with pytest.raises(RuntimeError, match="RETRY_AFTER_SECONDS"):
        get_settings()
    monkeypatch.setenv("RETRY_AFTER_SECONDS", "1")
    assert get_settings().retry_after_seconds == 1


def test_default_attempts_fit_in_the_deadline():
    s = get_settings()  # 3 * 1.5 + 2 * 0.2 = 4.9 <= 5
    assert (1 + s.provider_retries) * s.provider_attempt_timeout_seconds + (
        s.provider_retries * s.provider_retry_backoff_seconds
    ) <= s.refresh_deadline_seconds


def test_attempts_that_do_not_fit_in_the_deadline_refuse_to_start(monkeypatch):
    monkeypatch.setenv("PROVIDER_RETRIES", "3")  # 4 * 1.5 + 3 * 0.2 = 6.6 > 5
    with pytest.raises(RuntimeError) as exc:
        get_settings()
    for name in (
        "PROVIDER_RETRIES",
        "PROVIDER_ATTEMPT_TIMEOUT_SECONDS",
        "PROVIDER_RETRY_BACKOFF_SECONDS",
        "REFRESH_DEADLINE_SECONDS",
    ):
        assert name in str(exc.value)


def test_attempt_budget_boundary(monkeypatch):
    monkeypatch.setenv("PROVIDER_ATTEMPT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("PROVIDER_RETRY_BACKOFF_SECONDS", "0.5")
    monkeypatch.setenv("REFRESH_DEADLINE_SECONDS", "4")  # 3 * 1 + 2 * 0.5 = 4, exactly fits
    assert get_settings().refresh_deadline_seconds == 4
    monkeypatch.setenv("REFRESH_DEADLINE_SECONDS", "3.9")
    with pytest.raises(RuntimeError, match="REFRESH_DEADLINE_SECONDS"):
        get_settings()


def test_fresh_longer_than_max_stale_rejected(monkeypatch):
    monkeypatch.setenv("FORECAST_FRESH_SECONDS", "100")
    monkeypatch.setenv("FORECAST_MAX_STALE_SECONDS", "50")
    with pytest.raises(RuntimeError, match="FORECAST_FRESH_SECONDS"):
        get_settings()


def test_unknown_key_rejected(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PROVIDER_TIMEOUT=3\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    with pytest.raises(RuntimeError, match="PROVIDER_TIMEOUT"):
        get_settings()


def test_env_wins_over_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("RETRY_AFTER_SECONDS=9\nPROVIDER_RETRIES=1\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("RETRY_AFTER_SECONDS", "7")
    s = get_settings()
    assert s.retry_after_seconds == 7
    assert s.provider_retries == 1


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_base_url_rejected(monkeypatch, value):
    monkeypatch.setenv("PROVIDER_BASE_URL", value)
    with pytest.raises(RuntimeError, match=r"^PROVIDER_BASE_URL is required"):
        get_settings()


def test_empty_base_url_in_env_file_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("PROVIDER_BASE_URL")
    env_file = tmp_path / ".env"
    env_file.write_text("PROVIDER_BASE_URL=\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    with pytest.raises(RuntimeError, match=r"^PROVIDER_BASE_URL is required"):
        get_settings()


FLOAT_KEYS = [k for k in NUMERIC_KEYS if k not in ("PROVIDER_RETRIES", "RETRY_AFTER_SECONDS")]


@pytest.mark.parametrize("key", FLOAT_KEYS)
def test_infinite_values_rejected(monkeypatch, key):
    monkeypatch.setenv(key, "inf")
    with pytest.raises(RuntimeError, match=key):
        get_settings()
