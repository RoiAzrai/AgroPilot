"""Local fake of the Open-Meteo forecast endpoint for the NFR-2.3 measurement (design 5.11).

GET /v1/forecast answers any point with a valid 8-day body starting at today in
Asia/Jerusalem and counts the call; GET /calls returns {"calls": n}. Nothing here
contacts the real provider.

Usage, from services/weather-service:
    uv run python perf/fake_provider.py --port 8091
"""

import argparse
import json
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Jerusalem"
FORECAST_DAYS = 8
ET0 = "et0_fao_evapotranspiration"
RAIN = "precipitation_sum"


def forecast_body(today: date) -> dict:
    """Open-Meteo-shaped daily forecast: consecutive dates, units mm, finite values >= 0."""
    return {
        "latitude": 31.25,
        "longitude": 34.75,
        "utc_offset_seconds": 7200,
        "timezone": TIMEZONE,
        "daily_units": {"time": "iso8601", ET0: "mm", RAIN: "mm"},
        "daily": {
            "time": [(today + timedelta(days=i)).isoformat() for i in range(FORECAST_DAYS)],
            ET0: [round(2.5 + i / 10, 2) for i in range(FORECAST_DAYS)],
            RAIN: [0.0, 0.4, 2.0, 0.0, 5.5, 0.1, 0.0, 3.2],
        },
    }


class FakeProviderServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]):
        super().__init__(address, Handler)
        self.calls = 0
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: FakeProviderServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/v1/forecast":
            with self.server.lock:
                self.server.calls += 1
            self._json(200, forecast_body(datetime.now(ZoneInfo(TIMEZONE)).date()))
        elif path == "/calls":
            with self.server.lock:
                calls = self.server.calls
            self._json(200, {"calls": calls})
        else:
            self._json(404, {"error": "not found"})

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        pass  # one line per request would only add noise next to the measurement


def make_server(port: int, host: str = "127.0.0.1") -> FakeProviderServer:
    return FakeProviderServer((host, port))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args(argv)
    server = make_server(args.port, args.host)
    print(f"Fake provider on http://{args.host}:{args.port}/v1/forecast", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
