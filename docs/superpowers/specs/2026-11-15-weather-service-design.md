# Design: weather-service

Date: 2026-11-15. Branch: `p2`. Spec: `docs/task-p2.md`, sections "The
weather-service" (FR-2.3 to FR-2.8, NFR-2.3, Notes) and "Global
configurations".

## 1. Intent

`weather-service` (port 8001) gives the rest of AgroPilot the daily forecast
for a point: for each of the next `days` days, starting today, the date, ET0
(mm) and rain (mm). The planner turns it into an irrigation plan.

The one thing that matters above all (FR-2.8): **the service never answers
with a number the provider didn't give.** A forecast of zeros reads as "no
water needed", the worst possible bug in this system. Every doubt about the
provider's data is a provider failure, never a default.

The provider is Open-Meteo. The service caches per 0.1° cell in memory, so a
fresh forecast is served without calling the provider, and a failing provider
does not stop the planner: it gets a stale forecast (up to 24 h old) quickly,
or a clear 503.

## 2. Goals, non-goals, anti-goals

**Goals**

- G1. `GET /v1/forecast` as in FR-2.3/FR-2.4, with the response shape of the
  spec example.
- G2. One cached forecast per 0.1° cell, fresh for 3 h (FR-2.5), one provider
  call for concurrent requests in the same cell.
- G3. Provider failure: retries within a bounded time, then stale, then 503
  (FR-2.6, FR-2.7), with the pause described in 5.6 (a deliberate deviation).
- G4. FR-2.8 enforced by strict validation of every provider response.
- G5. NFR-2.3: fresh forecast p95 <= 100 ms at 10 req/s, measured without
  calling Open-Meteo.
- G6. Same error format, settings style and test discipline as
  `registry-service`, copied, not imported.

**Non-goals**

- No database, no persistence across restarts (a restart empties the cache).
- No knowledge of farms, plots or crops: coordinates and dates only.
- No more than one worker process (5.6 assumes it).
- No cache size limit / eviction (known limitation, README).
- No hourly data, no other weather variables.
- No full official perf session (pairs, monitors): three Poisson runs only.

**Anti-goals** (a failure even if everything "works")

- Any number in a response that did not come from the provider: a `0` for a
  missing value, a default day, a day carried over from yesterday.
- Yesterday served as today.
- A test that calls the real Open-Meteo.
- An Open-Meteo field name in a response, error body or the planner's view.
- The API key in a log line, an error body, or a committed file.
- A provider outage that makes every request wait for retries, so the planner
  times out instead of getting the stale forecast.

## 3. Constraints

- Own uv project in `services/weather-service`; `uv` commands from there.
  Never imports another service's code (`.claude/rules/repo.md`).
- Settings only from one `config.py` (pydantic-settings), `.env` never
  committed, `.env.example` with every key; a missing required key or an
  invalid combination is a clear startup error. Strict keys, like the
  registry (judgment log 30): an unknown key stops the service at startup.
- httpx for the provider call. Base URL, timeouts, retries, freshness and the
  API key come from `.env`.
- Tests never call Open-Meteo.
- One worker process (uvicorn without `--workers`).

## 4. Approaches considered

1. **Async (chosen).** `async def` endpoints, one `httpx.AsyncClient`
   created in the lifespan, the cache a plain dict on the event loop.
   Single-flight with one `asyncio.Future` per refreshing cell; the deadline
   with `asyncio.timeout`. All work is I/O waiting; one event loop means no
   thread races and no locks.
2. **Synchronous, like the registry.** `def` endpoints in the threadpool,
   `httpx.Client`, single-flight with `threading.Lock` + `Event`. Consistent
   with the registry, but the shared cache needs locks on every read, update
   and pause, and bounding waiters by the deadline is harder. Rejected: race
   bugs here would show up in production, not in tests.
3. **A cache library** (`cachetools`, `aiocache`). Rejected: the pause, the
   deadline, 24 h stale and past-day dropping are custom anyway; a library adds
   a dependency and saves no logic.

## 5. Decisions

Owner decisions W1-W10 are given; later decisions were agreed in the design
conversation. Items marked *(builder's call)* are the agent's proposals.

Owner decisions, for reference: W1 never serve a forecast older than 24 h;
W2 ask for 8 days; W3 echo the request's lat/lon; W4 drop past days in the
point's local time zone, 503 if fewer than `days` remain; W5 one cache entry
per cell, sliced per request; W6 single-flight per cell; W7 cell = floor to
0.1° without float/rounding errors; W8 rain = `precipitation_sum`, ET0 =
`et0_fao_evapotranspiration`, both mm; W9 `timezone=auto` (amended: keep the
time-zone name, 5.7); W10 errors as in the registry: problem+json,
`VALIDATION` 422 and `UNAVAILABLE` 503 with `Retry-After` from `.env` (5.8).

### 5.1 Layout

```
services/weather-service/
  pyproject.toml, uv.lock, .env.example, README.md
  config.py      settings, startup validation
  main.py        FastAPI app, lifespan (settings, httpx client, cache, clock)
  errors.py      problem+json (copied pattern from registry-service)
  models.py      request validation, response models
  cells.py       point -> 0.1° cell, cell center (W7)
  provider.py    the ONLY module that knows Open-Meteo: URL, params, field
                 names, response validation; returns a provider-neutral Forecast
  forecasts.py   cache, freshness, single-flight, deadline, pause, stale, 503
  tests/         conftest.py (fake provider, fake clock), test_*.py
  perf/          fake_provider.py, load_test.py, run_session.py (5.11)
```

*(builder's call)* File names; the boundaries (only `provider.py` sees
Open-Meteo names, only `forecasts.py` holds cache state) are binding.

Stack: Python 3.12, FastAPI, uvicorn, httpx, pydantic-settings, pytest
(+ `pytest-asyncio` or anyio's pytest plugin for async unit tests, builder's
pick).

### 5.2 Settings

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `PROVIDER_BASE_URL` | yes | (none; example `https://api.open-meteo.com/v1/forecast`) | Forecast endpoint. |
| `PROVIDER_API_KEY` | no | empty | Sent as `apikey` only when not empty. |
| `PROVIDER_ATTEMPT_TIMEOUT_SECONDS` | no | `1.5` | httpx timeout of one attempt. |
| `PROVIDER_RETRIES` | no | `2` | Retries after the first attempt (3 attempts total). |
| `PROVIDER_RETRY_BACKOFF_SECONDS` | no | `0.2` | Wait between attempts *(builder's call: constant)*. |
| `REFRESH_DEADLINE_SECONDS` | no | `5` | Bounds all attempts of one refresh together, and every wait on it. |
| `FORECAST_FRESH_SECONDS` | no | `10800` (3 h) | Fresh: served without calling the provider. |
| `FORECAST_MAX_STALE_SECONDS` | no | `86400` (24 h) | Older than this is never served (W1). |
| `FAILURE_PAUSE_SECONDS` | no | `60` | After a failed refresh, no provider call for this long (5.6). |
| `RETRY_AFTER_SECONDS` | no | `5` | `Retry-After` on a 503 outside a pause. |

Startup validation (clear `RuntimeError`, service does not start):
- `PROVIDER_BASE_URL` missing.
- `PROVIDER_ATTEMPT_TIMEOUT_SECONDS >= REFRESH_DEADLINE_SECONDS` (otherwise
  one attempt eats the budget and retries never happen).
- Negative values, `PROVIDER_RETRIES < 0`, or
  `FORECAST_FRESH_SECONDS > FORECAST_MAX_STALE_SECONDS` *(builder's call)*.
- Any unknown key (strict).

### 5.3 API

`GET /v1/forecast?lat={lat}&lon={lon}&days={days}`

- `lat`: number, -90..90; `lon`: number, -180..180; both required; NaN and
  infinity rejected. `days`: integer 1..7, default `7` *(builder's call: same
  default as the planner)*. Anything else: `422 VALIDATION` (FR-2.4).
- `200`:

```json
{
  "lat": 31.25,
  "lon": 34.79,
  "source": "open-meteo",
  "fetched_at": "2026-11-12T06:00:00Z",
  "stale": false,
  "days": [{ "date": "2026-11-12", "et0_mm": 3.1, "rain_mm": 0.0 }]
}
```

  - `lat`/`lon` echo the request (W3), not the cell or the provider's grid
    point.
  - `fetched_at`: when the service received the provider response (UTC,
    seconds, `Z`). For a stale answer, the original fetch time.
  - `days`: exactly `days` entries, consecutive dates, starting at the
    point's local today (5.7).
  - `source`: a constant of the provider module.
- `GET /health` -> `200 {"status": "ok"}`. Never calls the provider.
- Unknown route 404 `NOT_FOUND`, wrong method 405 `VALIDATION`, unexpected
  error 500 `UNAVAILABLE` without details: same handlers as the registry
  (judgment log 4, 15), copied.

### 5.4 Cells (W5, W7) and the provider point

- Cell index = `floor(x * 10)` computed exactly: `math.floor(Decimal(str(x)) * 10)`
  *(builder's call; any exact method is fine, never `round`)*. So `31.3 ->
  313`, `-0.05 -> -1`, `0.30000000000000004 -> 3`.
- Cell key = `(lat_index, lon_index)`.
- The provider is always asked for the **cell center**: `index / 10 + 0.05`,
  clamped to [-90, 90] and [-180, 180] (lat 90 -> 90, not 90.05; lon 180 ->
  180). The content of a cell never depends on which request came first.

### 5.5 Provider call and validation (`provider.py`; W2, W8, W9, FR-2.8)

Request: `latitude`, `longitude` (cell center), `daily=et0_fao_evapotranspiration,precipitation_sum`,
`forecast_days=8`, `timezone=auto`, plus `apikey` when set.

The response is accepted only if **all** of these hold; otherwise the attempt
is a provider failure (retry, then 5.6):

- HTTP 200 and a JSON object.
- `timezone` is a string that `zoneinfo.ZoneInfo` resolves.
- `daily_units.et0_fao_evapotranspiration == "mm"` and
  `daily_units.precipitation_sum == "mm"`.
- `daily.time`, `daily.et0_fao_evapotranspiration`, `daily.precipitation_sum`
  are lists of exactly 8 items each.
- Every date parses as ISO `YYYY-MM-DD`, and the 8 dates are consecutive.
- Every value is a real number: not `null`, not a bool, not a string, finite.
  *(builder's call)* Negative values are rejected too (physically impossible
  for both variables).
- A real `0.0` is valid and kept as is.

Result: a provider-neutral `Forecast(days=[Day(date, et0_mm, rain_mm)] * 8,
fetched_at, timezone_name)`. No Open-Meteo name leaves this module. Each
failed attempt logs a warning with the reason (timeout, status N, not JSON,
which check failed), never the API key; httpx's own request logging (which
prints URLs with query strings) is kept below INFO or the key is redacted.

Open-Meteo facts (variables, units, `timezone`, `apikey` and host for paid
plans) are confirmed against the docs and cited in the README.

### 5.6 Cache, refresh, deadline, pause (`forecasts.py`; W1, W5, W6, FR-2.5-2.7)

One entry per cell: `forecast | None`, `refreshing: Future | None`,
`paused_until | None`. Time comes from an injected clock (UTC, aware).

For a request in cell `c` at time `now`:

1. **Fresh** (`forecast` age < 3 h): serve it, `stale: false`. No provider call.
2. **Paused** (`now < paused_until`): fall back at once (step 5). No provider
   call.
3. **Refreshing**: wait on the shared future, at most `REFRESH_DEADLINE_SECONDS`
   (`asyncio.wait_for(asyncio.shield(future), ...)`); then use its outcome.
4. **Otherwise start the refresh** (single-flight, W6): up to
   `1 + PROVIDER_RETRIES` attempts, each with `PROVIDER_ATTEMPT_TIMEOUT_SECONDS`,
   `PROVIDER_RETRY_BACKOFF_SECONDS` between them, all inside
   `asyncio.timeout(REFRESH_DEADLINE_SECONDS)`.
   - Success: store the forecast, clear the pause, answer `stale: false`.
   - Failure (all attempts failed or the deadline ran out):
     `paused_until = now + FAILURE_PAUSE_SECONDS`, fall back (step 5).
   - Different cells refresh independently.
5. **Fall back**: if `forecast` exists and its age <= 24 h, serve it with
   `stale: true` and its original `fetched_at`. Otherwise `503 UNAVAILABLE`,
   `Retry-After` = the seconds left in the pause (rounded up, at least 1), or
   `RETRY_AFTER_SECONDS` outside a pause. Each fallback logs a warning with the
   cell and the reason.

**The pause is a deliberate deviation from the letter of FR-2.6**, which reads
as "every request retries twice, then serves stale". Owner's reason: the
planner has its own timeout; if every request waited for three attempts while
the provider is down, the planner would give up first and FR-2.13 (a stale
forecast still gives a plan) would break. The deviation goes in this design,
the README and the judgment log.

The deadline and the planner: the planner's timeout will be set above
`REFRESH_DEADLINE_SECONDS`, so a stale forecast or a 503 always arrives in time.

All of this assumes **one worker process**: the cache and single-flight live
in the process memory. README states it.

### 5.7 Building the answer (W4, W9 amended)

- Local today = `now` converted with `ZoneInfo(forecast.timezone_name)`. The
  time-zone *name* is kept, not the UTC offset, so a DST change during the
  24 h a forecast lives cannot shift "today" by an hour (W9 amended).
- Drop days before local today. The first remaining day must be **exactly**
  local today; if it is later (today is missing), or fewer than `days` remain:
  `503 UNAVAILABLE` (`Retry-After` as in 5.6 step 5). Never pad, never carry a
  day, never serve tomorrow as today. *(builder's call, the mirror of W4.
  A provider whose clock is a few minutes ahead around midnight gives a 503
  for those minutes only, and it heals by itself; it is not treated as a
  provider failure, so it starts no pause.)* Test: a forecast whose first
  date is tomorrow in the point's zone gives 503, never a 200.
- Return the first `days` days.
- Asking for 8 days (W2) means a forecast up to 24 h old still has 7 full
  days after dropping the past one (two days can drop only across a DST
  change; then `days=7` is a 503, correctly).

### 5.8 Errors

| Situation | Status | `code` |
| --- | --- | --- |
| Bad or missing `lat`/`lon`/`days` | 422 | `VALIDATION` |
| Provider failed / paused and no forecast <= 24 h | 503 + `Retry-After` | `UNAVAILABLE` |
| Fewer than `days` future days left | 503 + `Retry-After` | `UNAVAILABLE` |
| Unknown route | 404 | `NOT_FOUND` |
| Wrong method | 405 | `VALIDATION` |
| Unexpected exception | 500, no details | `UNAVAILABLE` |

Body: `application/problem+json` with exactly `type`, `title`, `status`,
`detail`, `code` (as `registry-service`). No provider text in any body.

### 5.9 Tests

Never the real Open-Meteo: the app's httpx client is built from a factory
the tests replace with an `httpx.MockTransport` fake provider; conftest also
sets `PROVIDER_BASE_URL` to an `.invalid` host and forces settings from the
environment (like the registry's `force_sqlite`). The clock is injected.

- Validation: every FR-2.4 boundary and type case, NaN/inf, default `days`.
- Cells: the 5.4 examples, negatives, edges (lat 90, lon 180, -180), center
  clamping.
- Provider validation: one test per 5.5 rule (missing field, `null`, string,
  bool, NaN, negative, arrays of different lengths, 7 dates, a gap in dates,
  unit `inch`, bad time zone, non-JSON, status 500, timeout). Each must give
  stale or 503, never a 200 with invented numbers. A real `0.0` is returned
  as `0.0`.
- Freshness: at 2:59 h no provider call; at 3:01 h one call.
- Stale: provider down, forecast 23 h old -> `stale: true`; 25 h old -> 503.
- Pause: after a failure, requests within 60 s make **no** provider call;
  `Retry-After` equals the seconds left; after 60 s exactly one request calls.
- Single-flight: N concurrent requests in one cell -> 1 provider call; two
  cells -> 2 calls.
- Retries and deadline: 3 attempts on repeated failure; a slow provider ends
  at about the deadline with fallback; waiters bounded by the deadline.
- Local today: a fetch on day D served after local midnight drops D; a
  UTC+14 zone and a DST-change case; fewer days left -> 503.
- Response: echoes request lat/lon; keys are exactly the spec's; no
  Open-Meteo names anywhere in the body.
- Settings: missing base URL, attempt timeout >= deadline, unknown key ->
  clear startup error.
- The API key never appears in logs (caplog) or bodies.
- `/health` works with the provider down.

### 5.10 README (service)

How to run; the settings table; the Open-Meteo variables and units with doc
links (W8); W1 and its reason (irrigation decisions are daily; after a day
the forecast may miss a change such as new rain); the pause and the deadline
as a deliberate deviation from FR-2.6 and why; the one-worker assumption; the
unbounded cache as a known limitation (random coordinates could grow memory);
a Mermaid sequence diagram of the flow in 5.6 *(builder's call: include the
optional diagram)*; how to run the NFR-2.3 measurement.

Two more points the README must explain (owner's request):

- **Why negative provider values are rejected, and the risk.** Neither rain
  nor ET0 can physically be below zero, so a negative value is treated as bad
  provider data (5.5). The risk: daily ET0 can, rarely, come out slightly
  negative on cold, humid nights (condensation). If that happens, the cell
  falls back to stale or 503 instead of serving that value.
- **Why rain = `precipitation_sum` and not `rain_sum`.** `precipitation_sum`
  includes showers and snowfall as well as rain, and all water that reaches
  the soil counts for irrigation.

### 5.11 NFR-2.3 measurement (`perf/`)

Goal: fresh forecast p95 <= 100 ms at 10 req/s, with **zero** calls to
Open-Meteo.

- `perf/fake_provider.py`: a local HTTP server on its own port that returns a
  valid 8-day Open-Meteo-shaped response for any point and counts the calls
  it receives (readable by the runner).
- The service runs with `PROVIDER_BASE_URL` pointing at the fake provider,
  set explicitly in the service's environment by the runner (environment
  wins over `.env`), one worker, no reload.
- `perf/load_test.py`: a **copy** of the registry's open-model load tool,
  adapted to `GET /v1/forecast?lat=..&lon=..&days=7` spread over several
  points (at least the four seed plots' coordinates: 31.25/34.79,
  31.26/34.80, 31.40/34.60, 31.41/34.61; builder may add more, covering
  several cells). Poisson arrivals at 10/s, load warm-up 20 s, measurement
  300 s, p95 with bootstrap CI, generator-lag check (INVALID run when lag p99
  > 10 ms), exit codes as the original.
- `perf/run_session.py` runs the session: setup (start fake provider and
  service), cache warm-up (one request per point, all must be 200
  `stale: false`), then **three Poisson runs, seeds 1-3** (no constant-rate
  pairs, no monitors: the same runs the official verdict used in P1 and in
  the registry move), then the summary (worst p95 across endpoints and runs,
  PASS only if all three runs pass), then the **zero-calls check**: the fake
  provider's call count did not change between the end of the cache warm-up
  and the end of the last run; otherwise the session FAILS.
- **Progress display** (owner's requirement):
  - One overall progress bar 0-100 % for the whole session (setup, cache
    warm-up, three runs, summary), with elapsed time and ETA.
  - A status line naming the measurement and its phase, e.g.
    `[run 2/3] Poisson seed 2 - measuring (180/300 s)`. Phases: setup, cache
    warm-up, load warm-up, measuring, summary, zero-calls check.
  - Every phase change written with a timestamp to
    `perf/results/<prefix>-phases.log`.
  - It must not affect the measurement: the load tool runs as a separate
    process; the runner updates the display every few seconds (progress from
    elapsed time against the known phase durations), outside any
    request-sending loop, writing to stderr. The load tool's generator-lag
    check must still pass and is the proof.
- Results in `perf/results/` (gitignored), never overwriting an existing
  prefix. Summary in the PR.

## 6. Files

New: everything under `services/weather-service/` (5.1), including
`.env.example` and `README.md`. Changed: `.gitignore` only if
`services/weather-service/perf/results/` is not already ignored;
`docs/judgment-log.md`; root `README.md` "Where to start" (one line for the new
service) *(builder's call)*.

## 7. Judgment log entries

- 32. A forecast older than 24 h is never served (W1), and why.
- 33. Pause after a failed refresh: a deliberate deviation from FR-2.6, and why.
- 34. One refresh deadline bounds all attempts and waiters; attempt timeout
  must be smaller.
- 35. Cell center sent to the provider, clamped; time-zone name instead of the
  UTC offset.

## 8. Left to the builder

- File names inside the layout, helper names, test file split.
- The async test plugin.
- Exact log wording.
- Extra measurement points beyond the four seed coordinates.

## 9. Open questions

None. The builder check asked about W10 (now listed in section 5) and about a
first provider date after local today (settled in 5.7).
