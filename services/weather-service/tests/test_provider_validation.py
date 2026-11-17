import copy
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from provider import SOURCE, Day, Forecast, ProviderError, parse_forecast

ET0 = "et0_fao_evapotranspiration"
RAIN = "precipitation_sum"
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)


PAST = 92  # past days the service asks for; the forecast days start at this index
TOTAL = PAST + 8


def valid_payload(start: date = date(2026, 11, 15), tz: str = "Asia/Jerusalem") -> dict:
    """100 days: 92 past days, then `start` (today) and the 8 forecast values."""
    first = start - timedelta(days=PAST)
    return {
        "latitude": 32.0,
        "longitude": 34.75,
        "utc_offset_seconds": 7200,
        "timezone": tz,
        "daily_units": {"time": "iso8601", ET0: "mm", RAIN: "mm"},
        "daily": {
            "time": [(first + timedelta(days=i)).isoformat() for i in range(TOTAL)],
            ET0: [round(3.0 + (i % 5) / 10, 2) for i in range(PAST)]
            + [1.5 + i / 10 for i in range(8)],
            RAIN: [1.0 if i % 7 == 0 else 0.0 for i in range(PAST)]
            + [0.0, 0.4, 2.0, 0.0, 5.5, 0.1, 0.0, 3.2],
        },
    }


REAL_MISSING = 25  # the real check on 2026-11-17: the 25 oldest past days were null


def realistic_payload(start: date = date(2026, 11, 15)) -> dict:
    """Like the real Open-Meteo answer (W27): the 25 oldest past days are null in
    both et0 and rain, so only the last 67 past days exist."""
    p = valid_payload(start)
    for i in range(REAL_MISSING):
        p["daily"][ET0][i] = None
        p["daily"][RAIN][i] = None
    return p


def test_valid_payload_parses():
    f = parse_forecast(valid_payload(), NOW)
    assert isinstance(f, Forecast)
    assert SOURCE == "open-meteo"
    assert len(f.days) == TOTAL
    assert sum(d.date < date(2026, 11, 15) for d in f.days) == PAST
    assert f.timezone_name == "Asia/Jerusalem"
    assert f.fetched_at == NOW
    p = valid_payload()
    first = date(2026, 11, 15) - timedelta(days=PAST)
    for i, d in enumerate(f.days):
        assert d == Day(first + timedelta(days=i), p["daily"][ET0][i], p["daily"][RAIN][i])
    assert f.days[PAST].date == date(2026, 11, 15)


def test_real_zero_is_kept():
    f = parse_forecast(valid_payload(), NOW)
    assert f.days[PAST].rain_mm == 0.0
    assert f.days[PAST + 3].rain_mm == 0.0


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


def _drop_first_day(p):
    for k in ("time", ET0, RAIN):
        p["daily"][k] = p["daily"][k][1:]


def _extra_day(p):
    last = date.fromisoformat(p["daily"]["time"][-1])
    p["daily"]["time"].append((last + timedelta(days=1)).isoformat())
    p["daily"][ET0].append(1.0)
    p["daily"][RAIN].append(0.0)


def _seven_all(p):
    for k in ("time", ET0, RAIN):
        p["daily"][k] = p["daily"][k][:7]


def _len(k, n):
    def mutate(p):
        arr = p["daily"][k]
        p["daily"][k] = arr[:n] if n < TOTAL else arr + [1.0]
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
    "null et0": _set(["daily", ET0, PAST + 2], None),
    "null rain": _set(["daily", RAIN, PAST + 2], None),
    "string et0": _set(["daily", ET0, PAST + 2], "3.1"),
    "string rain": _set(["daily", RAIN, PAST + 2], "3.1"),
    "bool et0": _set(["daily", ET0, PAST + 2], True),
    "bool rain": _set(["daily", RAIN, PAST + 2], True),
    "nan et0": _set(["daily", ET0, PAST + 2], float("nan")),
    "nan rain": _set(["daily", RAIN, PAST + 2], float("nan")),
    "inf et0": _set(["daily", ET0, PAST + 2], float("inf")),
    "inf rain": _set(["daily", RAIN, PAST + 2], float("inf")),
    "huge int et0": _set(["daily", ET0, PAST + 2], 10**400),
    "huge int rain": _set(["daily", RAIN, PAST + 2], 10**400),
    "negative et0": _set(["daily", ET0, PAST + 2], -0.1),
    "negative rain": _set(["daily", RAIN, PAST + 2], -0.1),
    "len 99/100/100": _len("time", 99),
    "len 100/99/100": _len(ET0, 99),
    "len 100/100/101": _len(RAIN, 101),
    "99 days": _drop_first_day,
    "101 days": _extra_day,
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


PAST_VALUE_CASES = {
    "null et0": (ET0, None),
    "null rain": (RAIN, None),
    "string et0": (ET0, "3.1"),
    "bool rain": (RAIN, True),
    "nan et0": (ET0, float("nan")),
    "inf rain": (RAIN, float("inf")),
    "huge int et0": (ET0, 10**400),
    "negative rain": (RAIN, -0.1),
}


TODAY = date(2026, 11, 15)


def past_dates(f: Forecast) -> list[date]:
    return [d.date for d in f.days if d.date < TODAY]


@pytest.mark.parametrize("name", list(PAST_VALUE_CASES))
@pytest.mark.parametrize("index", [0, 80, PAST - 1])
def test_bad_past_value_drops_it_and_every_older_day(name, index):
    key, value = PAST_VALUE_CASES[name]
    p = valid_payload()
    p["daily"][key][index] = value
    f = parse_forecast(p, NOW)
    kept = PAST - 1 - index
    # Only the run after the bad day is kept, up to yesterday (W27).
    assert past_dates(f) == [TODAY - timedelta(days=kept - i) for i in range(kept)]
    assert f.days == parse_forecast(valid_payload(), NOW).days[index + 1 :]


def test_realistic_payload_keeps_67_past_days():
    f = parse_forecast(realistic_payload(date(2026, 11, 17)), NOW)
    past = [d for d in f.days if d.date < date(2026, 11, 17)]
    assert len(past) == 67
    assert past[0].date == date(2026, 9, 11)
    assert past[-1].date == date(2026, 11, 16)
    assert len(f.days) == 67 + 8


def test_null_only_in_rain_makes_the_past_day_invalid():
    p = valid_payload()
    p["daily"][RAIN][85] = None
    f = parse_forecast(p, NOW)
    assert len(past_dates(f)) == PAST - 1 - 85
    assert past_dates(f)[0] == TODAY - timedelta(days=PAST - 1 - 85)


def test_null_only_in_et0_makes_the_past_day_invalid():
    p = valid_payload()
    p["daily"][ET0][85] = None
    assert len(past_dates(parse_forecast(p, NOW))) == PAST - 1 - 85


def test_invalid_yesterday_leaves_no_past_days():
    p = valid_payload()
    p["daily"][ET0][PAST - 1] = None
    f = parse_forecast(p, NOW)
    assert past_dates(f) == []
    assert [d.date for d in f.days] == [TODAY + timedelta(days=i) for i in range(8)]


def test_limited_past_logs_one_info_line(caplog):
    caplog.set_level("DEBUG", logger="provider")
    parse_forecast(realistic_payload(date(2026, 11, 17)), NOW)
    records = [r for r in caplog.records if r.name == "provider"]
    assert len(records) == 1
    assert records[0].levelname == "INFO"
    assert records[0].getMessage() == (
        "past days limited: 67 of 92 available, data starts 2026-09-11 "
        "(first missing: 2026-09-10, et0_fao_evapotranspiration and precipitation_sum)"
    )


def test_limited_past_log_names_only_the_bad_field(caplog):
    caplog.set_level("INFO", logger="provider")
    p = valid_payload()
    p["daily"][RAIN][PAST - 1] = None
    parse_forecast(p, NOW)
    [record] = [r for r in caplog.records if r.name == "provider"]
    assert record.getMessage() == (
        "no past days available (first missing: 2026-11-14, precipitation_sum)"
    )


def test_full_past_logs_nothing(caplog):
    caplog.set_level("DEBUG", logger="provider")
    parse_forecast(valid_payload(), NOW)
    assert [r for r in caplog.records if r.name == "provider"] == []


def test_bad_first_forecast_day_is_provider_error():
    p = valid_payload()
    p["daily"][ET0][PAST] = None
    with pytest.raises(ProviderError):
        parse_forecast(p, NOW)


def test_bad_date_in_past_part_is_provider_error():
    p = valid_payload()
    p["daily"]["time"][10] = "2026-02-30"
    with pytest.raises(ProviderError):
        parse_forecast(p, NOW)


def test_bad_past_and_bad_forecast_value_is_provider_error():
    p = valid_payload()
    p["daily"][ET0][0] = None
    p["daily"][RAIN][PAST + 1] = None
    with pytest.raises(ProviderError):
        parse_forecast(p, NOW)


def test_bad_past_and_bad_forecast_value_logs_no_info_line(caplog):
    caplog.set_level("DEBUG", logger="provider")
    p = valid_payload()
    p["daily"][ET0][0] = None
    p["daily"][RAIN][PAST + 1] = None
    with pytest.raises(ProviderError):
        parse_forecast(p, NOW)
    assert [r for r in caplog.records if r.name == "provider"] == []
