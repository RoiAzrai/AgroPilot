"""A registry + weather fake on httpx.MockTransport: no sockets. Routes are the real ones
(registry routers/plots.py and routers/catalogue.py, weather main.py)."""

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx

PLOT_ID = "6b1f0b0e-4a8e-4f4e-9d0e-0a1b2c3d4e5f"
SOIL_ID = "sand"
EMITTER_ID = "drip-1"
CROP_ID = "tomato"
FAKE_TODAY = date(2031, 6, 1)  # a fake date: nothing here may read a clock

ROUTES = {
    "plot": re.compile(r"^/v1/plots/([^/]+)$"),
    "soil": re.compile(r"^/v1/soils/([^/]+)$"),
    "emitter": re.compile(r"^/v1/emitters/([^/]+)$"),
    "crop": re.compile(r"^/v1/crops/([^/]+)$"),
    "forecast": re.compile(r"^/v1/forecast$"),
}
KNOWN_IDS = {"plot": PLOT_ID, "soil": SOIL_ID, "emitter": EMITTER_ID, "crop": CROP_ID}


@dataclass
class Override:
    status: int | None = None
    content: bytes | None = None  # raw body, replaces the default JSON
    headers: dict[str, str] | None = None
    delay: float = 0  # seconds before the answer starts
    slow_body: float = 0  # seconds between two chunks of the body
    exc: Exception | None = None  # raised instead of answering


class SlowBody(httpx.AsyncByteStream):
    def __init__(self, body: bytes, pause: float) -> None:
        self.body, self.pause = body, pause

    async def __aiter__(self):
        for i in range(0, len(self.body), 8):
            await asyncio.sleep(self.pause)
            yield self.body[i : i + 8]


def default_forecast(days: int, past_days: int, past_returned: int | None) -> dict:
    returned = past_days if past_returned is None else past_returned
    first = FAKE_TODAY - timedelta(days=returned)
    body = {
        "lat": 31.25,
        "lon": 34.75,
        "source": "open-meteo",
        "fetched_at": "2031-06-01T06:00:00Z",
        "stale": False,
        "days": [
            {
                "date": (first + timedelta(days=n)).isoformat(),
                "et0_mm": 4.0 + n / 10,
                "rain_mm": 0.0 if n % 2 == 0 else 1.5,
            }
            for n in range(days + returned)
        ],
    }
    if past_days > 0:
        body["past_days_returned"] = returned
    return body


class FakeUpstreams:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.overrides: dict[str, Override] = {}
        self.edits: dict[str, Callable[[dict], None]] = {}
        self.known = dict(KNOWN_IDS)  # ids the registry answers for
        self.past_returned: int | None = None  # None: as many past days as asked
        self.bodies = {
            "plot": {
                "id": PLOT_ID,
                "farm_id": "0d9b6a52-2f5c-4a39-8c53-5e0f6f0f7a11",
                "name": "North block",
                "area_m2": 1000,
                "crop_id": CROP_ID,
                "planting_date": "2031-04-13",
                "soil_id": SOIL_ID,
                "row_spacing_m": 1.5,
                "emitter_spacing_m": 0.4,
                "emitter_id": EMITTER_ID,
                "lat": 31.25,
                "lon": 34.79,
            },
            "soil": {"id": SOIL_ID, "name": "Sand", "available_water_mm_per_m": 83},
            "emitter": {"id": EMITTER_ID, "name": "Drip 1.6", "flow_lph": 1.6},
            "crop": {"id": CROP_ID, "name": "Tomato"},
        }

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def override(self, name: str, **kwargs) -> None:
        self.overrides[name] = Override(**kwargs)

    def edit(self, name: str, fn: Callable[[dict], None]) -> None:
        """Change the default JSON body of a route in place before it is served."""
        self.edits[name] = fn

    def calls(self, name: str) -> list[httpx.Request]:
        return [r for r in self.requests if ROUTES[name].match(r.url.path)]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for name, pattern in ROUTES.items():
            match = pattern.match(request.url.path)
            if match:
                break
        else:
            return httpx.Response(404)
        override = self.overrides.get(name, Override())
        if override.exc:
            raise override.exc
        if override.delay:
            await asyncio.sleep(override.delay)
        if override.content is not None:
            body = override.content
            ok = override.status or 200
        elif name != "forecast" and match[1] != self.known[name]:
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        else:
            data = self.default_body(name, request)
            if name in self.edits:
                self.edits[name](data)
            body = json.dumps(data).encode()  # not httpx's json=: it refuses NaN
            ok = override.status or 200
        headers = {"content-type": "application/json", **(override.headers or {})}
        if override.slow_body:
            return httpx.Response(ok, headers=headers, stream=SlowBody(body, override.slow_body))
        return httpx.Response(ok, headers=headers, content=body)

    def default_body(self, name: str, request: httpx.Request) -> dict:
        if name != "forecast":
            return json.loads(json.dumps(self.bodies[name]))
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        return default_forecast(int(q["days"]), int(q.get("past_days", 0)), self.past_returned)
