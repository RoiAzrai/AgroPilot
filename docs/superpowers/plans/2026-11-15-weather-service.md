# weather-service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `services/weather-service` (port 8001) that serves the daily ET0/rain forecast per point from Open-Meteo, cached per 0.1° cell, never inventing a number (FR-2.8), with a bounded, provider-friendly failure path and an NFR-2.3 measurement that never calls Open-Meteo.

**Architecture:** FastAPI with `async def` endpoints and one `httpx.AsyncClient` from the lifespan. `provider.py` is the only module that knows Open-Meteo and turns its response into a validated, provider-neutral `Forecast`; `forecasts.py` holds the in-memory cache (fresh / single-flight / deadline / pause / stale / 503); `main.py` wires it to HTTP. One worker process.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, pydantic-settings, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-15-weather-service-design.md` (read it before any task; §n refers to its sections). Also `docs/task-p2.md` "The weather-service".

## Global Constraints

- All commands from `services/weather-service` (`uv sync`, `uv run pytest`, `uv run python ...`). Never import code from `services/registry-service`; copy patterns.
- Each task touches **only** the files its **Files** block lists. Anything else: stop and ask.
- Tests never call the real Open-Meteo (MockTransport or the local fake provider only). Never read or create `.env`.
- FR-2.8: never a number the provider didn't give. Missing, `null`, non-number, bool, NaN/inf, negative, wrong lengths, date gap, unit not `mm`, unknown time zone = provider failure. A real `0.0` is valid.
- Open-Meteo field names appear only in `provider.py`, `perf/fake_provider.py` and their tests.
- Settings (§5.2): `PROVIDER_BASE_URL` (required), `PROVIDER_API_KEY=""`, `PROVIDER_ATTEMPT_TIMEOUT_SECONDS=1.5`, `PROVIDER_RETRIES=2`, `PROVIDER_RETRY_BACKOFF_SECONDS=0.2`, `REFRESH_DEADLINE_SECONDS=5`, `FORECAST_FRESH_SECONDS=10800`, `FORECAST_MAX_STALE_SECONDS=86400`, `FAILURE_PAUSE_SECONDS=60`, `RETRY_AFTER_SECONDS=5`. Strict keys.
- Errors (§5.8): `application/problem+json` with exactly `type`, `title`, `status`, `detail`, `code`; `VALIDATION` 422, `UNAVAILABLE` 503 + `Retry-After`, `NOT_FOUND` 404, 405 `VALIDATION`, 500 `UNAVAILABLE` without details.
- The API key never appears in logs, error bodies or committed files.
- Dependencies: `fastapi~=0.115`, `uvicorn~=0.32`, `httpx~=0.28`, `pydantic-settings~=2.6`; dev: `pytest~=9.2`, `anyio` pytest plugin (via `anyio`, already a FastAPI dependency) for async tests.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Coordinates on cell boundaries and negatives** (`31.3`, `-0.0`, `-33.95`, `0.1+0.2`): the right cell, never off by one. Pinned: Task 2 tests.
2. **Provider answers 200 with HTML, an empty body, or a JSON array**: provider failure, never a 500. Pinned: Task 4 tests.
3. **Just after local midnight with a fresh (2 h old) forecast**: yesterday dropped, still 7 days, `200`. Pinned: Task 5 test `test_fresh_forecast_after_local_midnight_still_has_seven_days`.
4. **Provider that answers after the deadline**: the request falls back at the deadline; the late answer is not served to it. Pinned: Task 6 test `test_slow_provider_falls_back_at_deadline`.
5. **Garbage query values** (`lat=31.25abc`, `days=7.5`, `lat=` empty, `lat=nan`): 422 `VALIDATION`, never 500. Pinned: Task 7 tests.

## Steps only the owner does (not planned for the agent)

- **O1.** Write `services/weather-service/.env` (from `.env.example`, real `PROVIDER_BASE_URL`). After Task 7.
- **O2.** Manual check against the real Open-Meteo: run the service, `GET /v1/forecast?lat=31.25&lon=34.79&days=7`, and compare `et0_mm`/`rain_mm` with Open-Meteo's own answer for the cell center (31.25, 34.75) with `timezone=auto`. After Task 8.
- **O3.** Official NFR-2.3 measurement: `uv run python perf/run_session.py --prefix official` (about 17 minutes). After Task 10.

---

### Task 1: Project scaffold and settings

**Files:**
- Create: `services/weather-service/pyproject.toml`, `uv.lock`, `config.py`, `.env.example`, `tests/__init__.py` (only if needed), `tests/conftest.py`, `tests/test_config.py`
- Modify: `.gitignore` (repo root): add `services/weather-service/perf/results/`

**Interfaces:**
- Produces: `config.ENV_FILE: Path` (= folder of `config.py` / `.env`); `class Settings(BaseSettings)` with the fields of Global Constraints in lower snake case (`provider_base_url: str`, `provider_api_key: str = ""`, `provider_attempt_timeout_seconds: float = 1.5`, `provider_retries: int = 2`, `provider_retry_backoff_seconds: float = 0.2`, `refresh_deadline_seconds: float = 5`, `forecast_fresh_seconds: float = 10800`, `forecast_max_stale_seconds: float = 86400`, `failure_pause_seconds: float = 60`, `retry_after_seconds: int = 5`), strict (unknown keys rejected); `def get_settings() -> Settings` reading environment, then `ENV_FILE`, at call time; raises `RuntimeError` with a message naming the key for each startup error (§5.2).
- `tests/conftest.py` autouse fixture `isolated_settings`: sets `PROVIDER_BASE_URL=http://provider.invalid/v1/forecast` and patches `config.ENV_FILE` to a missing tmp path.

- [ ] **Step 1:** `uv init --no-package` style project (match registry's `pyproject.toml` shape: `[tool.uv] package = false`, pytest `pythonpath = ["."]`, `testpaths = ["tests"]`), add the dependencies of Global Constraints. Expected: `uv sync` ok.
- [ ] **Step 2: Failing tests** in `tests/test_config.py`:
  - `test_defaults`: only `PROVIDER_BASE_URL` set → every default equals Global Constraints.
  - `test_missing_base_url_is_clear`: delenv → `RuntimeError` matching `^PROVIDER_BASE_URL is required`.
  - `test_attempt_timeout_must_be_below_deadline`: `PROVIDER_ATTEMPT_TIMEOUT_SECONDS=5`, `REFRESH_DEADLINE_SECONDS=5` → `RuntimeError` mentioning both keys; `1.5`/`5` is fine.
  - `test_negative_values_rejected` (parametrized over every numeric key, value `-1`) → `RuntimeError` naming the key.
  - `test_fresh_longer_than_max_stale_rejected` → `RuntimeError`.
  - `test_unknown_key_rejected`: a tmp `.env` with `PROVIDER_TIMEOUT=3` → error (strict).
  - `test_env_wins_over_env_file`.
- [ ] **Step 3:** run → FAIL (`No module named 'config'`).
- [ ] **Step 4:** implement `config.py`; write `.env.example` with all ten keys, safe values, the Open-Meteo URL, an empty `PROVIDER_API_KEY`, and the comment that unknown keys stop the service at startup.
- [ ] **Step 5:** `uv run pytest -q` → all pass. Commit — "weather-service: scaffold and settings".

### Task 2: Cells (§5.4)

**Files:** Create `cells.py`, `tests/test_cells.py`.

**Interfaces:**
- Produces: `Cell = tuple[int, int]`; `def cell_of(lat: float, lon: float) -> Cell` (exact floor to 0.1°, e.g. via `math.floor(Decimal(str(x)) * 10)`; never `round`); `def cell_center(cell: Cell) -> tuple[float, float]` = `(index / 10 + 0.05)` per axis, clamped to [-90, 90] / [-180, 180], returned as floats rounded to 2 decimals for display stability (`31.25`, not `31.250000000000004`).

- [ ] **Step 1: Failing tests:** `cell_of(31.25, 34.79) == (312, 347)`; `cell_of(31.3, 0) == (313, 0)`; `cell_of(-0.05, -0.05) == (-1, -1)`; `cell_of(-0.0, 0.0) == (0, 0)`; `cell_of(0.1 + 0.2, 0) == (3, 0)`; `cell_of(-33.95, 151.2) == (-340, 1512)`; `cell_of(90, 180) == (900, 1800)`; `cell_of(-90, -180) == (-900, -1800)`. `cell_center((312, 347)) == (31.25, 34.75)`; `cell_center((900, 1800)) == (90.0, 180.0)`; `cell_center((-900, -1800)) == (-89.95, -179.95)`; `cell_center((-1, -1)) == (-0.05, -0.05)`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** pass. **Step 5:** commit — "weather-service: 0.1° cells and cell center".

### Task 3: Provider response validation — FR-2.8 first (§5.5)

**Files:** Create `provider.py`, `tests/test_provider_validation.py`.

**Interfaces:**
- Produces in `provider.py`: `SOURCE = "open-meteo"`; `FORECAST_DAYS = 8`; `@dataclass(frozen=True) class Day: date: datetime.date; et0_mm: float; rain_mm: float`; `@dataclass(frozen=True) class Forecast: days: tuple[Day, ...]; fetched_at: datetime; timezone_name: str`; `class ProviderError(Exception)` (message = the reason, no secrets); `def parse_forecast(payload: object, fetched_at: datetime) -> Forecast`.
- Test helper (in the test file): `valid_payload(start: date = date(2026, 11, 15), tz: str = "Asia/Jerusalem") -> dict` — 8 consecutive dates, units `mm`, finite non-negative values, including one `0.0` rain.

- [ ] **Step 1: Failing tests** (each invalid case: `pytest.raises(ProviderError)`):
  - `test_valid_payload_parses`: 8 `Day`s, exact values, `timezone_name == "Asia/Jerusalem"`.
  - `test_real_zero_is_kept`: `rain_mm == 0.0` for the zero day.
  - parametrized `test_invalid_payload_is_provider_error` over: not a dict (list, string, `None`); missing `daily`; missing `daily_units`; missing each of `time`/`et0_fao_evapotranspiration`/`precipitation_sum`; a `null` value in each array; a string `"3.1"`; a bool `True`; `float("nan")`; `float("inf")`; a negative `-0.1` in each array; lengths 7/8/8, 8/7/8, 8/8/9; only 7 days in all three; a date gap (day 4 missing, 8 items); a duplicated date; an unparsable date `"2026-13-01"`; unit `"inch"` for each variable; missing unit; `timezone` missing, not a string, `"Mars/Olympus"`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement `parse_forecast` (only this module uses the Open-Meteo names). **Step 4:** pass. **Step 5:** commit — "weather-service: strict provider validation (FR-2.8)".

### Task 4: Provider HTTP call (§5.5)

**Files:** Modify `provider.py`; Create `tests/test_provider_fetch.py`.

**Interfaces:**
- Consumes: `Settings`, `parse_forecast`, `Forecast`, `ProviderError`.
- Produces: `async def fetch_forecast(client: httpx.AsyncClient, settings: Settings, lat: float, lon: float, now: Callable[[], datetime]) -> Forecast` — ONE attempt: `GET settings.provider_base_url` with params `latitude`, `longitude`, `daily=et0_fao_evapotranspiration,precipitation_sum`, `forecast_days=8`, `timezone=auto`, plus `apikey` only if not empty; `timeout=settings.provider_attempt_timeout_seconds`; non-200, non-JSON body, `httpx.TimeoutException`, `httpx.TransportError` → `ProviderError`; `fetched_at=now()` taken when the response arrives. Each failure logs one warning on logger `provider` with the reason. The `httpx` and `httpcore` loggers are set to WARNING at import so URLs with the key are never logged.

- [ ] **Step 1: Failing tests** with `httpx.MockTransport`:
  - `test_request_params`: captured request has exactly the params above (no `apikey` when empty); with `provider_api_key="k"` → `apikey=k`.
  - parametrized failures → `ProviderError`: status 500, 429, 404; 200 with HTML body; 200 with empty body; 200 with `[]`; transport raising `httpx.ConnectError`; `httpx.ReadTimeout`.
  - `test_key_never_logged`: key `secret-key-123`, a failing response, `caplog` at DEBUG for all loggers → the key appears in no record.
  - `test_success_returns_forecast_with_now`.
- [ ] **Step 2–4:** FAIL → implement → pass. **Step 5:** commit — "weather-service: one provider attempt over httpx".

### Task 5: Forecast cache — fresh, refresh, stale, local today (§5.6 steps 1, 4, 5 without retries/pause; §5.7)

**Files:** Create `forecasts.py`, `tests/test_forecasts.py`, `tests/fakes.py` (FakeClock, scripted fetch).

**Interfaces:**
- Consumes: `Cell`, `Day`, `Forecast`, `ProviderError`, `Settings`.
- Produces in `forecasts.py`: `Clock = Callable[[], datetime]`; `Fetch = Callable[[Cell], Awaitable[Forecast]]` (one attempt for that cell); `@dataclass(frozen=True) class Answer: days: list[Day]; fetched_at: datetime; stale: bool`; `class Unavailable(Exception)` with attribute `retry_after: int`; `class ForecastCache` with `__init__(self, fetch: Fetch, settings: Settings, clock: Clock)` and `async def get(self, cell: Cell, days: int) -> Answer`.
- `tests/fakes.py`: `FakeClock(start: datetime)` with `now()` and `advance(seconds: float)`; `ScriptedFetch` returning/raising a queued sequence and counting `calls`.
- Rules in this task: fresh (age < `forecast_fresh_seconds`) → served, no fetch; otherwise one fetch; success → stored, `stale=False`; `ProviderError` → stale if age ≤ `forecast_max_stale_seconds`, else `Unavailable(retry_after=settings.retry_after_seconds)`. Answer days: local today from `ZoneInfo(timezone_name)`, drop earlier days; first remaining must equal local today and at least `days` must remain, else `Unavailable(retry_after_seconds)`; return the first `days`.

- [ ] **Step 1: Failing tests:** `test_first_request_fetches`; `test_fresh_served_without_fetch` (2 h 59 m → 0 extra calls); `test_expired_refetches` (3 h 01 m → 1 call); `test_failure_serves_stale_within_24h` (23 h, `stale=True`, original `fetched_at`); `test_failure_after_24h_is_unavailable` (25 h → `Unavailable`, `retry_after == 5`); `test_failure_without_forecast_is_unavailable`; `test_fresh_forecast_after_local_midnight_still_has_seven_days` (fetched 23:00 local, asked 01:00 next day, `days=7` → 7 days starting the new local date); `test_today_missing_is_unavailable` (first date = local tomorrow → `Unavailable`, never 200); `test_fewer_days_than_requested_is_unavailable`; `test_utc_plus_14_zone` (`Pacific/Kiritimati`: local date ahead of UTC); `test_dst_change_uses_zone_name` (`America/New_York`, forecast fetched before the November DST change, asked after it: local today correct); `test_slices_days` (days=1..7); `test_cells_are_independent`.
- [ ] **Step 2–4:** FAIL → implement → pass. **Step 5:** commit — "weather-service: cache with freshness, stale and local today".

### Task 6: Retries, deadline, single-flight, pause (§5.6 steps 2–4)

**Files:** Modify `forecasts.py`; Create `tests/test_refresh.py`.

**Interfaces:**
- Consumes/keeps: everything from Task 5 (signatures unchanged).
- Adds: up to `1 + provider_retries` attempts with `provider_retry_backoff_seconds` between them, all inside `asyncio.timeout(refresh_deadline_seconds)`; one in-flight refresh per cell (an `asyncio.Future` shared by concurrent requests, each waiter bounded by `refresh_deadline_seconds` via `asyncio.wait_for(asyncio.shield(fut), ...)`); after a failed refresh `paused_until = now + failure_pause_seconds` — while paused, no fetch: stale or `Unavailable(retry_after=ceil(seconds left), min 1)`; success clears the pause. Fallback warnings logged on logger `forecasts` with the cell and reason.

- [ ] **Step 1: Failing tests** (backoff `0`/tiny, deadlines ≤ 0.5 s for speed): `test_three_attempts_on_repeated_failure` (calls == 3); `test_success_on_third_attempt` (`stale=False`); `test_retries_setting_respected` (`provider_retries=0` → 1 call); `test_slow_provider_falls_back_at_deadline` (fetch sleeps 2 s, deadline 0.3 s → returns stale/`Unavailable` in < 0.6 s; the late result is not in the answer); `test_single_flight_one_call` (10 concurrent `get` same cell → 1 call, all get the same answer); `test_two_cells_two_calls`; `test_waiters_bounded_by_deadline`; `test_pause_makes_no_calls` (failure, then requests at +1 s, +30 s, +59 s → no new calls, stale served); `test_pause_retry_after_is_seconds_left` (no stale: at +20 s `retry_after == 40`); `test_after_pause_one_request_retries` (+61 s, 5 concurrent → 1 call); `test_success_clears_pause`; `test_fresh_beats_pause` (fresh forecast is served even if a pause is set).
- [ ] **Step 2–4:** FAIL → implement → pass (full suite too). **Step 5:** commit — "weather-service: retries within a deadline, single-flight, failure pause".

### Task 7: HTTP API (§5.3, §5.8)

**Files:** Create `errors.py`, `models.py`, `main.py`, `tests/test_api.py`; Modify `tests/conftest.py` (add API fixtures).

**Interfaces:**
- Consumes: `get_settings`, `cell_of`, `cell_center`, `fetch_forecast`, `SOURCE`, `ForecastCache`, `Answer`, `Unavailable`.
- Produces: `errors.py` copied from the registry pattern (`problem()`, `AppError`, handlers for `RequestValidationError`, Starlette 404/405, unexpected 500) plus a handler for `Unavailable` → 503 `UNAVAILABLE`, `detail` `"Forecast unavailable"`, header `Retry-After: str(retry_after)`. `models.py`: response models `DayOut(date, et0_mm, rain_mm)`, `ForecastOut(lat, lon, source, fetched_at, stale, days)`; `fetched_at` serialized as `YYYY-MM-DDTHH:MM:SSZ`. `main.py`: `app`; `def make_client(settings: Settings) -> httpx.AsyncClient` and `def utc_now() -> datetime` (module-level, so tests replace them); lifespan builds settings, client, `ForecastCache(fetch=lambda cell: fetch_forecast(client, settings, *cell_center(cell), utc_now), ...)`; `GET /health` → `{"status": "ok"}`; `GET /v1/forecast` with `lat: float` (ge -90, le 90, finite), `lon: float` (ge -180, le 180, finite), `days: int = 7` (ge 1, le 7).
- conftest additions: `assert_problem(response, status, code) -> dict` (copied from the registry's conftest: status, `Content-Type`, exact body keys, `code`); `fake_provider` fixture (MockTransport handler serving `valid_payload`-shaped data for any point, scriptable to fail, counting calls; any host other than `provider.invalid` fails the test), `clock` fixture (FakeClock patched into `main.utc_now`), `client` fixture (`TestClient(app)` with `main.make_client` patched to use the MockTransport).

- [ ] **Step 1: Failing tests:** `test_spec_example_shape` (keys exactly `lat, lon, source, fetched_at, stale, days`; day keys exactly `date, et0_mm, rain_mm`; `source == "open-meteo"`; echoes `lat=31.25`, `lon=34.79`); `test_provider_asked_for_cell_center` (31.25/34.75); `test_default_days_is_seven`; parametrized `test_validation_422` (`lat=-90.1`, `90.1`, `lon=-180.1`, `180.1`, `days=0`, `8`, `7.5`, `lat=31.25abc`, `lat=` empty, `lat=nan`, `lon=inf`, missing `lat`, missing `lon`) → `assert_problem(..., 422, "VALIDATION")`; boundaries `lat=-90`, `90`, `lon=-180`, `180`, `days=1`, `7` → 200; `test_no_provider_names_in_body` (no `et0_fao`, `precipitation`, `daily` in the text); `test_provider_down_no_cache_is_503` (status, `Retry-After` header, body has no provider text); `test_provider_down_with_cache_is_stale_200`; `test_health_with_provider_down`; `test_unknown_route_404`, `test_wrong_method_405`; `test_startup_fails_without_base_url`; `test_key_not_in_logs_or_body`.
- [ ] **Step 2–4:** FAIL → implement → pass. **Step 5: Smoke run without any real provider:** `uv run uvicorn main:app --port 8001` starts with `PROVIDER_BASE_URL=http://127.0.0.1:9/v1/forecast` set in the environment, `curl -s localhost:8001/health` → `{"status":"ok"}`, `curl -si 'localhost:8001/v1/forecast?lat=31.25&lon=34.79'` → `503` with `Retry-After` (nothing listens on port 9). Stop it. **Step 6:** commit — "weather-service: HTTP API and problem+json errors".

### Task 8: READMEs (§5.10)

**Files:** Create `services/weather-service/README.md`; Modify repo-root `README.md` (one line for the new service).

- [ ] **Step 1:** Write the service README with every item of §5.10: run; settings table; Open-Meteo variables and units **confirmed against https://open-meteo.com/en/docs** with links (`et0_fao_evapotranspiration`, `precipitation_sum`, `daily_units`, `timezone=auto`, `apikey` and the paid host); W1 and its reason; the pause and deadline as a deliberate deviation from FR-2.6 and why; why negatives are rejected and the cold-humid-night ET0 risk; why `precipitation_sum` and not `rain_sum`; one worker process; unbounded cache as a known limitation; a Mermaid sequence diagram of §5.6 (request, fresh, paused, single-flight wait, attempts, deadline, stale, 503); how to run the NFR-2.3 measurement (filled by Task 9/10 references).
- [ ] **Step 2: Verify:** `grep -n "precipitation_sum\|rain_sum\|FR-2.6\|one worker\|known limitation\|mermaid" services/weather-service/README.md` shows each topic; every setting key from `.env.example` appears in the README. **Step 3:** commit — "weather-service: README".

### Task 9: NFR-2.3 measurement tools (§5.11, without the progress display)

**Files:** Create `perf/fake_provider.py`, `perf/load_test.py`, `perf/run_session.py`, `tests/test_perf_tools.py`.

**Interfaces:**
- `perf/fake_provider.py`: `python perf/fake_provider.py --port 8091` — stdlib `ThreadingHTTPServer`; `GET /v1/forecast` → a valid 8-day Open-Meteo-shaped body starting at local today for `timezone: "Asia/Jerusalem"`, for any point; `GET /calls` → `{"calls": n}` (count of forecast requests).
- `perf/load_test.py`: a copy of `services/registry-service/perf/load_test.py` adapted: requests are `GET /v1/forecast?lat=..&lon=..&days=7` over `POINTS` (at least `(31.25, 34.79)`, `(31.26, 34.80)`, `(31.40, 34.60)`, `(31.41, 34.61)`; one endpoint row per point); no id discovery; same CLI options, lag check (INVALID when lag p99 > 10 ms), bootstrap CI and exit codes (0 pass, 1 fail, 2 invalid, 3 setup).
- `perf/run_session.py --prefix P [--warmup 20] [--duration 300] [--service-port 8001] [--provider-port 8091]`: refuses an existing `perf/results/P-*`; starts the fake provider and `uvicorn main:app` (one worker) with `PROVIDER_BASE_URL=http://127.0.0.1:<provider-port>/v1/forecast` in the service's environment; cache warm-up (each point once, all `200`, `stale: false`); records `calls` after warm-up; runs `perf/load_test.py` for seeds 1, 2, 3 (Poisson) writing `perf/results/P-poisson-seedN.json`; summary (worst p95 across endpoints and runs, PASS only if all three pass); zero-calls check (`calls` unchanged since warm-up, else FAIL); stops both processes; exit 0 pass / 1 fail / 2 invalid / 3 setup.

- [ ] **Step 1: Failing tests** (no network beyond localhost): `test_fake_provider_body_passes_strict_validation` (its body passes `provider.parse_forecast`); `test_fake_provider_counts_calls`; `test_session_summary` (pure function over three result dicts: PASS/FAIL/INVALID and worst p95); `test_zero_calls_check` (pure function).
- [ ] **Step 2–4:** FAIL → implement → pass. **Step 5: Dry run:** `uv run python perf/run_session.py --prefix dry --warmup 2 --duration 10` → exit 0, three result files, zero-calls check PASS. Remove `perf/results/dry-*`. **Step 6:** commit — "weather-service: NFR-2.3 measurement with a fake provider".

### Task 10: Progress display for the measurement runner (§5.11)

**Files:** Modify `perf/run_session.py`; Create `perf/progress.py`, `tests/test_progress.py`.

**Interfaces:**
- `perf/progress.py`: `@dataclass Phase(name: str, label: str, seconds: float)`; `def session_plan(warmup: float, duration: float) -> list[Phase]` (setup, cache warm-up, then per run: load warm-up + measuring, then summary, zero-calls check; labels like `[run 2/3] Poisson seed 2`); `def overall_fraction(plan, phase_index: int, phase_elapsed: float) -> float` (0..1, monotone, 1.0 at the end); `def eta_seconds(plan, phase_index, phase_elapsed) -> float`; `def status_line(plan, phase_index, phase_elapsed, total_elapsed) -> str` (bar, percent, elapsed, ETA, and e.g. `[run 2/3] Poisson seed 2 - measuring (180/300 s)`); `class PhaseLog(path)` with `log(phase: Phase)` appending `<ISO timestamp> <label> - <name>` lines.
- `run_session.py`: a display task in the runner process redraws `status_line` to **stderr** every 2 s (never inside the load tool, which is a separate process); every phase change goes to `perf/results/<prefix>-phases.log`.

- [ ] **Step 1: Failing tests:** `test_fraction_monotone_and_complete`; `test_eta_zero_at_end`; `test_status_line_example` (`"[run 2/3] Poisson seed 2 - measuring (180/300 s)"` in the line for that state); `test_phase_log_lines` (timestamped, one per phase change, all phases in order).
- [ ] **Step 2–4:** FAIL → implement → pass. **Step 5: Dry run** as in Task 9: the bar reaches 100 %, the status line names every phase, `perf/results/dry-phases.log` lists all phases with timestamps, and each run's lag check passes (lag p99 ≤ 10 ms, no INVALID). Remove `perf/results/dry-*`. **Step 6:** commit — "weather-service: session progress display".
