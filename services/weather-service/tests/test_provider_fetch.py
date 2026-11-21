import logging
from datetime import datetime, timezone

import httpx
import pytest

from config import Settings
from provider import Forecast, ProviderError, fetch_forecast
from test_provider_validation import TOTAL, valid_payload

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)
URL = "http://provider.invalid/v1/forecast"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_settings(key: str = "") -> Settings:
    return Settings(provider_base_url=URL, provider_api_key=key)


async def call(handler, key: str = "") -> Forecast:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await fetch_forecast(client, make_settings(key), 32.05, 34.75, lambda: NOW)


@pytest.mark.anyio
async def test_request_params():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=valid_payload())

    await call(handler)
    await call(handler, key="k")
    assert len(seen) == 2
    assert seen[0].method == "GET"
    assert dict(seen[0].url.params) == {
        "latitude": "32.05",
        "longitude": "34.75",
        "daily": "et0_fao_evapotranspiration,precipitation_sum",
        "forecast_days": "8",
        "past_days": "92",
        "timezone": "auto",
    }
    assert dict(seen[1].url.params)["apikey"] == "k"


def _raise(exc):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


FAILURES = [
    lambda r: httpx.Response(500),
    lambda r: httpx.Response(429),
    lambda r: httpx.Response(404),
    lambda r: httpx.Response(200, text="<html>oops</html>"),
    lambda r: httpx.Response(200, content=b""),
    lambda r: httpx.Response(200, json=[]),
    _raise(httpx.ConnectError("boom")),
    _raise(httpx.ReadTimeout("slow")),
    _raise(httpx.TooManyRedirects("loop")),
    _raise(httpx.InvalidURL("bad")),
    lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"not gzip"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("handler", FAILURES)
async def test_failures_raise_provider_error(handler):
    with pytest.raises(ProviderError):
        await call(handler)


@pytest.mark.anyio
async def test_key_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ProviderError) as info:
        await call(lambda r: httpx.Response(500), key="secret-key-123")
    assert "secret-key-123" not in str(info.value)
    assert "secret-key-123" not in caplog.text
    for record in caplog.records:
        assert "secret-key-123" not in record.getMessage()


@pytest.mark.anyio
async def test_success_returns_forecast_with_now():
    forecast = await call(lambda r: httpx.Response(200, json=valid_payload()))
    assert forecast.fetched_at == NOW
    assert len(forecast.days) == TOTAL


@pytest.mark.anyio
async def test_key_never_logged_on_transport_error(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ProviderError) as info:
        await call(_raise(httpx.ConnectError("secret-key-123")), key="secret-key-123")
    assert "secret-key-123" not in str(info.value)
    assert "secret-key-123" not in caplog.text
    for record in caplog.records:
        assert "secret-key-123" not in record.getMessage()


@pytest.mark.anyio
async def test_attempt_timeout_is_passed():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json=valid_payload())

    await call(handler)
    expected = make_settings().provider_attempt_timeout_seconds
    assert set(seen[0].values()) == {expected}


@pytest.mark.anyio
async def test_unexpected_parse_error_becomes_provider_error(monkeypatch):
    def boom(payload, fetched_at):
        raise KeyError("secret-key-123")

    monkeypatch.setattr("provider.parse_forecast", boom)
    with pytest.raises(ProviderError) as info:
        await call(lambda r: httpx.Response(200, json=valid_payload()))
    assert "secret-key-123" not in str(info.value)
