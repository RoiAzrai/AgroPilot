import math
import re
from pathlib import Path

import pytest

import config
from config import Settings, get_settings

ENV_EXAMPLE = Path(config.__file__).parent / ".env.example"
TIMEOUT_KEYS = [
    "REGISTRY_TIMEOUT_SECONDS",
    "WEATHER_TIMEOUT_SECONDS",
    "WEATHER_REFRESH_DEADLINE_SECONDS",
]
FLOAT_KEYS = TIMEOUT_KEYS + ["DEPLETION_FRACTION_OVERRIDE"]
NUMERIC_KEYS = FLOAT_KEYS + ["MAX_DAILY_RUN_MINUTES", "RETRY_AFTER_SECONDS"]


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    # A developer's .env and shell env must never leak into these tests.
    for key in [*NUMERIC_KEYS, "REGISTRY_URL", "WEATHER_URL"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REGISTRY_URL", "http://registry.invalid")
    monkeypatch.setenv("WEATHER_URL", "http://weather.invalid")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "no-such.env")


def test_defaults():
    s = get_settings()
    assert s.registry_url == "http://registry.invalid"
    assert s.weather_url == "http://weather.invalid"
    assert s.registry_timeout_seconds == 3
    assert s.weather_timeout_seconds == 6
    assert s.weather_refresh_deadline_seconds == 5
    assert s.retry_after_seconds == 5
    assert s.max_daily_run_minutes == 1440
    assert s.depletion_fraction_override is None


@pytest.mark.parametrize("key", ["REGISTRY_URL", "WEATHER_URL"])
def test_missing_required_key_names_it(monkeypatch, key):
    monkeypatch.delenv(key)
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize("key", ["REGISTRY_URL", "WEATHER_URL"])
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_required_key_names_it(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize("key", ["REGISTRY_URL", "WEATHER_URL"])
@pytest.mark.parametrize("value", ["127.0.0.1:8000", "localhost", "ftp://host", "registry"])
def test_url_without_http_scheme_names_key(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=f"{key}.*http"):
        get_settings()


@pytest.mark.parametrize("key", ["REGISTRY_URL", "WEATHER_URL"])
@pytest.mark.parametrize("value", ["http://host:1", "https://host"])
def test_url_with_http_or_https_passes(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    assert getattr(get_settings(), key.lower()) == value


def test_retry_after_minimum_is_1(monkeypatch):
    monkeypatch.setenv("RETRY_AFTER_SECONDS", "1")
    assert get_settings().retry_after_seconds == 1
    monkeypatch.setenv("RETRY_AFTER_SECONDS", "0")
    with pytest.raises(RuntimeError, match="RETRY_AFTER_SECONDS"):
        get_settings()


@pytest.mark.parametrize("key", NUMERIC_KEYS)
@pytest.mark.parametrize("value", ["", "abc", "1.5x"])
def test_empty_or_non_numeric_value_names_key(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize("key", FLOAT_KEYS)
@pytest.mark.parametrize("value", ["inf", "-inf", "nan"])
def test_inf_nan_rejected(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize("key", TIMEOUT_KEYS)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_timeouts_must_be_positive(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=key):
        get_settings()


@pytest.mark.parametrize("value", ["1", "1440"])
def test_max_daily_run_minutes_edges_pass(monkeypatch, value):
    monkeypatch.setenv("MAX_DAILY_RUN_MINUTES", value)
    assert get_settings().max_daily_run_minutes == int(value)


@pytest.mark.parametrize("value", ["0", "1441", "-5"])
def test_max_daily_run_minutes_out_of_range(monkeypatch, value):
    monkeypatch.setenv("MAX_DAILY_RUN_MINUTES", value)
    with pytest.raises(RuntimeError, match="MAX_DAILY_RUN_MINUTES"):
        get_settings()


@pytest.mark.parametrize("value", ["0", "1", "0.5"])
def test_override_edges_pass(monkeypatch, value):
    monkeypatch.setenv("DEPLETION_FRACTION_OVERRIDE", value)
    assert get_settings().depletion_fraction_override == float(value)


@pytest.mark.parametrize("value", ["-0.1", "1.1"])
def test_override_out_of_range(monkeypatch, value):
    monkeypatch.setenv("DEPLETION_FRACTION_OVERRIDE", value)
    with pytest.raises(RuntimeError, match="DEPLETION_FRACTION_OVERRIDE"):
        get_settings()


@pytest.mark.parametrize("timeout", ["5", "4"])
def test_weather_timeout_must_exceed_refresh_deadline(monkeypatch, timeout):
    monkeypatch.setenv("WEATHER_TIMEOUT_SECONDS", timeout)
    monkeypatch.setenv("WEATHER_REFRESH_DEADLINE_SECONDS", "5")
    with pytest.raises(RuntimeError) as exc:
        get_settings()
    assert "WEATHER_TIMEOUT_SECONDS" in str(exc.value)
    assert "WEATHER_REFRESH_DEADLINE_SECONDS" in str(exc.value)


def test_weather_timeout_above_deadline_passes(monkeypatch):
    monkeypatch.setenv("WEATHER_TIMEOUT_SECONDS", "6")
    monkeypatch.setenv("WEATHER_REFRESH_DEADLINE_SECONDS", "5")
    assert get_settings().weather_timeout_seconds == 6


def test_unknown_key_in_env_file_is_startup_error(tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("REGISTRY_TIMEOUT_SECOND=3\n")  # typo
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    with pytest.raises(RuntimeError, match="(?i)REGISTRY_TIMEOUT_SECOND"):
        get_settings()


def test_env_file_values_are_read(tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("MAX_DAILY_RUN_MINUTES=600\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    assert get_settings().max_daily_run_minutes == 600


def test_env_example_has_every_key_and_only_local_urls():
    keys, values = set(), {}
    # A key may be commented out (`# KEY=value`): the optional override is unset by default.
    for match in re.finditer(r"^#? ?([A-Z_]+)=(.*)$", ENV_EXAMPLE.read_text(), re.MULTILINE):
        keys.add(match[1])
        values[match[1]] = match[2].strip()
    assert keys == {name.upper() for name in Settings.model_fields}
    assert values["REGISTRY_URL"].startswith("http://127.0.0.1")
    assert values["WEATHER_URL"].startswith("http://127.0.0.1")


def test_env_example_is_a_valid_config(tmp_path, monkeypatch):
    for key in ("REGISTRY_URL", "WEATHER_URL"):
        monkeypatch.delenv(key)
    monkeypatch.setattr(config, "ENV_FILE", ENV_EXAMPLE)
    s = get_settings()
    assert s.weather_timeout_seconds > s.weather_refresh_deadline_seconds
    assert math.isfinite(s.registry_timeout_seconds)
