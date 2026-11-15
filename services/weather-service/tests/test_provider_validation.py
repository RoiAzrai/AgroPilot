import copy
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from provider import SOURCE, Day, Forecast, ProviderError, parse_forecast

ET0 = "et0_fao_evapotranspiration"
RAIN = "precipitation_sum"
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)


def valid_payload(start: date = date(2026, 11, 15), tz: str = "Asia/Jerusalem") -> dict:
    return {
        "latitude": 32.0,
        "longitude": 34.75,
        "utc_offset_seconds": 7200,
        "timezone": tz,
        "daily_units": {"time": "iso8601", ET0: "mm", RAIN: "mm"},
        "daily": {
            "time": [(start + timedelta(days=i)).isoformat() for i in range(8)],
            ET0: [1.5 + i / 10 for i in range(8)],
            RAIN: [0.0, 0.4, 2.0, 0.0, 5.5, 0.1, 0.0, 3.2],
        },
    }


def test_valid_payload_parses():
    f = parse_forecast(valid_payload(), NOW)
    assert isinstance(f, Forecast)
    assert SOURCE == "open-meteo"
    assert len(f.days) == 8
    assert f.timezone_name == "Asia/Jerusalem"
    assert f.fetched_at == NOW
    p = valid_payload()
    for i, d in enumerate(f.days):
        assert d == Day(date(2026, 11, 15) + timedelta(days=i), p["daily"][ET0][i], p["daily"][RAIN][i])


def test_real_zero_is_kept():
    f = parse_forecast(valid_payload(), NOW)
    assert f.days[0].rain_mm == 0.0
    assert f.days[3].rain_mm == 0.0


def _set(path, value):
    def mutate(p):
        node = p
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return mutate


def _del(path):
    def mutate(p):
        node = p
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return mutate


def _gap(p):
    del p["daily"]["time"][3]
    p["daily"]["time"].append("2026-11-23")


def _dup(p):
    p["daily"]["time"][4] = p["daily"]["time"][3]


def _seven_all(p):
    for k in ("time", ET0, RAIN):
        p["daily"][k] = p["daily"][k][:7]


def _len(k, n):
    def mutate(p):
        arr = p["daily"][k]
        p["daily"][k] = arr[:n] if n < 8 else arr + [1.0]
    return mutate


CASES = {
    "list": lambda p: [],
    "string": lambda p: "{}",
    "none": lambda p: None,
    "missing daily": _del(["daily"]),
    "missing daily_units": _del(["daily_units"]),
    "missing time": _del(["daily", "time"]),
    "missing et0": _del(["daily", ET0]),
    "missing rain": _del(["daily", RAIN]),
    "null et0": _set(["daily", ET0, 2], None),
    "null rain": _set(["daily", RAIN, 2], None),
    "string et0": _set(["daily", ET0, 2], "3.1"),
    "string rain": _set(["daily", RAIN, 2], "3.1"),
    "bool et0": _set(["daily", ET0, 2], True),
    "bool rain": _set(["daily", RAIN, 2], True),
    "nan et0": _set(["daily", ET0, 2], float("nan")),
    "nan rain": _set(["daily", RAIN, 2], float("nan")),
    "inf et0": _set(["daily", ET0, 2], float("inf")),
    "inf rain": _set(["daily", RAIN, 2], float("inf")),
    "huge int et0": _set(["daily", ET0, 2], 10**400),
    "huge int rain": _set(["daily", RAIN, 2], 10**400),
    "negative et0": _set(["daily", ET0, 2], -0.1),
    "negative rain": _set(["daily", RAIN, 2], -0.1),
    "len 7/8/8": _len("time", 7),
    "len 8/7/8": _len(ET0, 7),
    "len 8/8/9": _len(RAIN, 9),
    "only 7 days": _seven_all,
    "date gap": _gap,
    "duplicate date": _dup,
    "bad date": _set(["daily", "time", 1], "2026-13-01"),
    "compact date": _set(["daily", "time", 1], "20261116"),
    "inch et0": _set(["daily_units", ET0], "inch"),
    "inch rain": _set(["daily_units", RAIN], "inch"),
    "missing et0 unit": _del(["daily_units", ET0]),
    "missing rain unit": _del(["daily_units", RAIN]),
    "missing timezone": _del(["timezone"]),
    "timezone not string": _set(["timezone"], 3),
    "unknown timezone": _set(["timezone"], "Mars/Olympus"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_invalid_payload_is_provider_error(name):
    mutate = CASES[name]
    payload = copy.deepcopy(valid_payload())
    if name in ("list", "string", "none"):
        payload = mutate(payload)
    else:
        mutate(payload)
    with pytest.raises(ProviderError):
        parse_forecast(payload, NOW)


def test_negative_zero_becomes_zero():
    p = valid_payload()
    p["daily"][ET0][1] = -0.0
    p["daily"][RAIN][1] = -0.0
    day = parse_forecast(p, NOW).days[1]
    assert day.et0_mm == 0.0
    assert day.rain_mm == 0.0
    assert math.copysign(1, day.et0_mm) == 1
    assert math.copysign(1, day.rain_mm) == 1
