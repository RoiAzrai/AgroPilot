# Design: planner-service

Date: 2026-11-18. Branch: `p2`. Spec: `docs/task-p2.md`, section "The
planner-service" (FR-2.9 to FR-2.14, Notes, the example table) and "Global
configurations". Domain: `.claude/skills/irrigation-calc-reference/`
(SKILL.md, references/cases.md, references/decisions.md I1-I22), sources in
`services/planner-service/docs/research/fao56.md`. Upstream contracts:
`services/registry-service` (API below) and `services/weather-service/README.md`
(W20-W22, W27).

Owner decisions P1-P11 are given (2026-11-18 consultation); their wording as
given is in Appendix A, which is the source. Items marked
*(builder's call)* are the agent's calls, all approved by the owner. The
questions Q1-Q5 are decided (section 9); nothing is open.

## 1. Intent

`planner-service` (port 8002) answers the grower's question: *should I water
this plot today, and for how many minutes?* For a plot it returns a plan for
the next 1-7 days, starting today: per day the weather (ET0, rain), the crop
factor, the soil bucket, and how many litres and minutes to run the drip
system (FR-2.9, FR-2.10).

Two things matter above all:

- **Every number comes from the engine, exactly as the skill writes it**
  (FR-2.11; task Notes: no AI model computes or adjusts any number). The
  engine is pure functions, tested first against every hand-calculated case.
- **Never a plan of zeros** (FR-2.14). `run_minutes: 0` means "the bucket
  does not need water today", so a zero that comes from missing data tells a
  grower not to water a field that may need it. When an upstream is down or
  slow, or answers something unexpected, the planner answers with an error,
  never a partial or default plan.

The planner keeps no state. It does not know today's bucket level, so the
grower gives it (`bucket_start`, P5), helped by a suggestion computed from the
date of their last irrigation (P3, I14-I22).

## 2. Goals, non-goals, anti-goals

**Goals**

- G1. `GET /v1/plots/{id}/plan?days=1..7` (default 7; FR-2.9, FR-2.10) with the
  day fields of P1, and `bucket_start` (P5).
- G2. `GET /v1/plots/{id}/bucket-suggestion?last_irrigation=YYYY-MM-DD` (P3, P4).
- G3. Every number per the skill, including the new daily cap I23 (P11).
- G4. Errors as in FR-2.12, FR-2.14 and P6, in the problem+json format of the
  registry and weather services.
- G5. Upstream failures are fast and clear: no retries (P8), bounded by the
  timeouts of P7.
- G6. README with a JSON example (task: "add an example to the service
  README"), optional Mermaid diagram.

**Non-goals**

- Storing irrigations, plans or bucket levels (decisions.md "Future
  improvement": not built).
- Caching forecasts or registry data in the planner. weather-service already
  caches; the registry is fast (NFR-1.1). *(builder's call)*
- An NFR measurement: the task gives the planner none.
- Crops other than tomato and bell pepper (the registry has these two).

**Anti-goals** (would make it a failure even if it "works")

- A plan where a missing or failed input became a 0, a default ET0, a default
  soil value, or a skipped day.
- An irrigation number not traceable, by hand, to the formulas in SKILL.md.
- Hard-coded soil water, URLs, timeouts or the cap (Units: "Never hard-code
  it"; Global configurations).
- A plan that tells the grower to run the drip system for more minutes than a
  day has (P11).

## 3. Constraints

- Separate uv project in `services/planner-service`, own `.venv`, `.env`,
  `.env.example`. Talks to the registry and weather over HTTP only; imports
  nothing from them (repo rules).
- Settings in one `config.py` (pydantic-settings), strict keys: an unknown key
  stops the service at startup; missing or invalid values (including `inf`,
  `nan`) stop it too, as in weather-service.
- FastAPI, async `httpx` (P10), same error handlers and problem+json body as
  the registry and weather (`type`, `title`, `status`, `detail`, `code`).
- The agent never reads `.env`. Tests never call the real registry, weather
  or Open-Meteo.
- The registry gives crops as `{id, name}` only. The crop coefficients (stage
  lengths, Kc, Zmax, p) are therefore the skill's table, kept in the planner's
  engine, keyed by the registry crop id (`tomato`, `bell-pepper`).
  *(builder's call: the skill table names the second crop "pepper"; the
  engine keys it by the registry id `bell-pepper`)*

## 4. Approaches considered

1. **Pure engine + thin async service** (chosen). `engine/` is plain Python:
   dataclasses in, dataclasses out, no I/O, no clock, no settings object
   (values are passed in). `upstream.py` fetches and validates; `main.py`
   wires it. The engine is built and tested first against cases.md, with no
   HTTP at all. Every number is traceable to one function.
2. **Engine inside the request handlers.** Fewer files, but the cases can only
   be tested through HTTP fakes, and a formula change touches web code.
   Rejected: FR-2.11 traceability and "built and tested first" both need the
   engine on its own.
3. **Precompute plans** (a background job per plot, served from memory).
   Rejected: needs a clock, a schedule and state, and `bucket_start` is per
   request anyway. The plan costs microseconds; the time is in the upstream
   calls.

## 5. Decisions

### 5.1 Layout *(builder's call)*

```
services/planner-service/
  config.py          Settings (5.2)
  main.py            app, lifespan (one httpx.AsyncClient), routes, logging setup
  errors.py          problem+json handlers (copied from weather-service)
  upstream.py        registry and weather calls + validation (5.5)
  models.py          response models (5.3, 5.4)
  engine/
    crops.py         the skill's crop table, keyed by registry crop id
    season.py        season day i, stage, Kc (Eq. 66), Zr (Eq. 8-3)
    bucket.py        TAW/RAW/ETc, the daily bucket step, I23 cap
    drip.py          litres, run_minutes, the rounding rule (I19/I20)
    plan.py          a whole plan: days -> PlanDay list
    suggestion.py    I14-I18, I22
  tests/
  docs/research/fao56.md   (exists)
  README.md, .env.example, pyproject.toml
```

### 5.2 Settings (`config.py`)

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `REGISTRY_URL` | yes | none (example `http://127.0.0.1:8000`) | registry-service base URL |
| `WEATHER_URL` | yes | none (example `http://127.0.0.1:8001`) | weather-service base URL |
| `REGISTRY_TIMEOUT_SECONDS` | no | `3` | Whole registry call, P7 |
| `WEATHER_TIMEOUT_SECONDS` | no | `6` | Whole weather call, P7 |
| `MAX_DAILY_RUN_MINUTES` | no | `1440` | I23 daily cap, P11 |
| `DEPLETION_FRACTION_OVERRIDE` | no | unset | I21: replaces p for every crop, 0..1 |
| `WEATHER_REFRESH_DEADLINE_SECONDS` | no | `5` | Weather-service's refresh deadline, copied here for the P7 startup check (Q2) |
| `RETRY_AFTER_SECONDS` | no | `5` | `Retry-After` of a 503 when the upstream sent none *(builder's call)* |

Startup checks (fail fast, clear message):

- Missing or empty URL; non-finite or non-positive timeout; unknown key.
- `WEATHER_TIMEOUT_SECONDS` must be above `WEATHER_REFRESH_DEADLINE_SECONDS`
  (P7, Q2). That key is strict like the others (finite, positive) and is in
  `.env.example`; keeping it equal to weather's own deadline is the operator's
  job.
- `MAX_DAILY_RUN_MINUTES` in `1..1440` *(builder's call: a day has 1440
  minutes; above it the cap means nothing)*.
- `DEPLETION_FRACTION_OVERRIDE`, when set, in `[0, 1]` and finite.

### 5.3 API: the plan

`GET /v1/plots/{id}/plan?days={days}&bucket_start={bucket_start}`

- `days`: integer 1..7, default 7 (FR-2.9). `bucket_start`: number 0..1,
  default 1.0, finite (P5, I15). Anything else: `422 VALIDATION` (FR-2.12).
- `id`: passed to the registry as is. The registry answers 404 for an unknown
  or malformed id (it maps a non-UUID to 404), so the planner does not parse
  it *(builder's call)*.

`200` (North block style, values illustrative):

```json
{
  "plot_id": "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002",
  "crop": "tomato",
  "bucket_start": 1.0,
  "fetched_at": "2026-11-18T06:00:00Z",
  "stale": false,
  "days": [
    {
      "date": "2026-11-18",
      "stage": "mid",
      "et0_mm": 6.0,
      "rain_mm": 0.0,
      "kc": 1.15,
      "litres": 6900,
      "run_minutes": 248,
      "bucket_mm": 115.6,
      "bucket_capacity_mm": 122.5,
      "stale": false
    }
  ]
}
```

- Day fields: the FR-2.10 set plus `rain_mm`, `bucket_capacity_mm`, `stage`
  (P1). `bucket_mm` is the level at the end of the day (`TAW − Dr_end`),
  `bucket_capacity_mm` is that day's TAW. `stage` is one of `not_planted`,
  `ini`, `dev`, `mid`, `late`, `ended`.
- `date` and the number of days come from the weather answer, never from the
  planner's clock *(builder's call: weather-service owns "local today" for the
  point; the planner computes the season day from those dates)*.
- After the season (P2): `stage: "ended"`, `litres: 0`, `run_minutes: 0`,
  `kc: null`, `bucket_mm: null`. `bucket_capacity_mm` is `null` too
  *(builder's call: P2 does not list it, and TAW has no meaning without a
  crop)*. `et0_mm`, `rain_mm` and `stale` are still the forecast's.
- Each day's `stale` is the forecast's `stale` (one forecast serves all days,
  so FR-2.13 "every affected day" is every day).
- Top-level `plot_id`, `crop`, `bucket_start`, `fetched_at`, `stale` *(builder's
  call: the frontend shows "forecast from <time>, stale" once, FR-2.17)*.
- Output precision (Q3): computed unrounded, served with `kc` to 4 decimals
  and `bucket_mm`, `bucket_capacity_mm` to 2, rounded half up with the I19
  rule. `et0_mm` and `rain_mm` pass through exactly as weather sent them.
- A day before planting (Q4): `stage: "not_planted"`, `litres: 0`,
  `run_minutes: 0`, `kc: null`, `bucket_mm: null`, `bucket_capacity_mm: null`,
  as after the season. `et0_mm`, `rain_mm` and `stale` are the forecast's.
  (The registry accepts a planting date up to UTC+14, so for a few hours the
  planting date can be tomorrow at the point.)

### 5.4 API: the bucket suggestion (P3, P4)

`GET /v1/plots/{id}/bucket-suggestion?last_irrigation=YYYY-MM-DD`

`200`:

```json
{
  "plot_id": "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002",
  "last_irrigation": "2026-11-14",
  "suggestion": 0.7031,
  "exact": true,
  "reason": null,
  "past_days_requested": 3,
  "past_days_returned": 3,
  "stale": false
}
```

Rules, in this order (checks 1-4 are the fixed order of checks; 5 on is the calculation). Rationale: a future date is invalid input for any plot; the other checks depend on the plot, so they run after it is fetched, and "no suggestion because the season ended" is the true answer (I18).

1. `last_irrigation` not a valid `YYYY-MM-DD` date, or a date clearly in the
   future (later than the latest date on Earth, UTC+14, as the registry checks
   planting dates) → `422 VALIDATION` (I15). Checked before any upstream call,
   so it is a 422 even when an upstream is down (Q1).
2. Fetch the plot from the registry → `404 NOT_FOUND` if missing, `503
   UPSTREAM_UNAVAILABLE` if the registry is down (5.6).
3. Season ended (today's season day > season length) → `200`,
   `suggestion: null`, `exact: false`, `reason: "season_ended"` (I18, P4).
   Wins over the checks below. "Today" comes from the one weather call (Q1,
   below).
4. D before planting, or more than 92 days back, or in the future of the
   point's local today (passed step 1 but within the UTC+14 margin) → `422
   VALIDATION` (I15). "Today" is the point's local today, learned from the
   weather answer (Q1).
5. Otherwise continue to the calculation → `200`:
   - D = today or D = yesterday → `suggestion: 1.0`, `exact: true`, no past
     days needed: `past_days_requested: 0`, `past_days_returned: 0` (I15, I22).
   - Otherwise `past_days_requested = today − D − 1` (I22; the count needed,
     not the 92 asked from weather: weather is called once with
     `days=1&past_days=92`, today is the date after its past days, and only
     the last `past_days_requested` past days are used; `past_days_returned`
     is how many of those weather had). If all came back: the simulation of
     SKILL.md "Bucket suggestion", `exact: true`. If fewer (at least 1): start
     full at the **start** of the first returned day; if the run reaches empty
     on any day, `exact: true` with the value of the run; otherwise
     `suggestion: null`, `exact: false`, `reason: "insufficient_past_weather"`.
     0 returned (D < yesterday): `insufficient_past_weather` (I22, P4).
   - `stale`: the weather answer's `stale` *(builder's call: a stale entry
     still has valid past days; the grower should know the numbers are from an
     old fetch)*.

`suggestion` is a fraction of **today's** TAW (I14), clamped to [0, 1].
Precision: 4 decimals *(builder's call, as in cases.md 4a: 0.7031)*, rounded
half up with the I19 rule.

### 5.5 Upstream calls (`upstream.py`; P6, P7, P8, P10)

Registry API used (all exist today, `routers/plots.py`, `routers/catalogue.py`):

| Call | Fields used |
| --- | --- |
| `GET /v1/plots/{id}` | `area_m2`, `crop_id`, `planting_date`, `soil_id`, `row_spacing_m`, `emitter_spacing_m`, `emitter_id`, `lat`, `lon` |
| `GET /v1/soils/{soil_id}` | `available_water_mm_per_m` |
| `GET /v1/emitters/{emitter_id}` | `flow_lph` |
| `GET /v1/crops/{crop_id}` | `id` (exists; coefficients come from the engine table) |

Weather: `GET /v1/forecast?lat&lon&days=N` for the plan;
`days=1&past_days=92` for the suggestion, one call (Q1). "Today" is the date
after the past days. With past days the weather answer has `1 + past_days_returned`
consecutive days.

Order (P10): the plot first (its ids and lat/lon are needed), then soil,
emitter, crop and weather in parallel (`asyncio.gather`), one shared
`httpx.AsyncClient`. No retries (P8).

Timeouts (P7): each call is bounded as a whole by `asyncio.timeout(…)` with
`REGISTRY_TIMEOUT_SECONDS` or `WEATHER_TIMEOUT_SECONDS` *(builder's call:
httpx timeouts are per phase (connect, read, ...), so a slow trickle could
exceed them; the task says "doesn't answer in time")*. Worst case for a plan:
3 s (plot) + 6 s (parallel) ≈ 9 s; the frontend's timeout must be above it.

Validation: every upstream answer is parsed strictly. Registry numbers must be
finite and positive (area, spacings, flow, soil water). Weather: exactly the
requested number of days (plus `past_days_returned` past days), consecutive
dates, `et0_mm` and `rain_mm` finite and ≥ 0. Anything else is "an unexpected
upstream answer" → 500 (P6). The planner never fills a missing number.

Crop coefficients: the registry crop id must be in the engine table, else
`422` (P9, kept as approved; see the flag in section 9). The `detail` says the
crop has no coefficients and that this is a data problem, not a request problem.

### 5.6 Errors (P6, FR-2.12, FR-2.14)

| Situation | Status | `code` |
| --- | --- | --- |
| Bad `days`, `bucket_start` or `last_irrigation`; I15 date rules | 422 | `VALIDATION` |
| Registry 404 for the plot | 404 | `NOT_FOUND` |
| Registry or weather: connection error, timeout, 5xx | 503 + `Retry-After` | `UPSTREAM_UNAVAILABLE` |
| Crop without coefficients (P9); `detail` says it is a data problem, not a request problem | 422 | `VALIDATION` |
| Any other unexpected upstream answer (other 4xx, bad JSON, missing field, wrong day count, non-finite number, a 404 for soil/emitter/crop) | 500, no details | `INTERNAL` *(builder's call: the registry and weather use `UNAVAILABLE` for 500; here that would read like an outage, so a distinct code)* |
| Unknown route / wrong method | 404 / 405 | `NOT_FOUND` / `VALIDATION` |

- The 503 `detail` names the service: `"registry-service is unavailable"` or
  `"weather-service is unavailable"` (FR-2.14). If both fail, the first one
  noticed is named *(builder's call)*.
- `Retry-After`: the weather's own value when it sent one (its pause), else
  `RETRY_AFTER_SECONDS` *(builder's call)*.
- A failure anywhere means no plan at all: never a partial plan.

### 5.7 The engine (`engine/`)

Everything in SKILL.md and decisions.md I1-I22, as written. Additions:

**I23, the daily cap (P11).** Today a refill can need more minutes than a day
has: North block (loam 175, tomato, Zr 0.70 → TAW 122.5, RAW 49 mm; emitters
1.5 × 0.4 m at 1.0 L/h = 1.67 mm/h) needs about 1,800 minutes for one refill.

```
cap_mm = MAX_DAILY_RUN_MINUTES * flow_lph / (row_spacing_m * emitter_spacing_m) / 60
refilling = False                                    # carried day to day, within one plan
each day (after the rain step of SKILL.md):
    if refilling or Dr_start + ETc > RAW:
        need = Dr_start + ETc                        # the full refill
        I = min(need, cap_mm)
        Dr_end = min(need - I, TAW)                  # I17
        refilling = Dr_end > 0
    else:
        I = 0;  Dr_end = min(Dr_start + ETc, TAW)
```

- **When the continuation stops:** on the first day whose remaining need
  (`Dr_start + ETc`, after that day's rain) fits under the cap; that day ends
  full (`Dr_end = 0`). Rain on a continuation day lowers the need (it is
  subtracted in `Dr_start`). The season ending also stops it (an `ended` day
  never irrigates) *(builder's call)*.
- **Each day:** a capped day has `run_minutes = MAX_DAILY_RUN_MINUTES`,
  `litres = round(cap_mm · area)`, `bucket_mm = TAW − Dr_end` (above RAW's
  level is not guaranteed). The finishing day is an ordinary refill day.
- **Stateless:** the continuation lives inside one plan. A new request starts
  from `bucket_start`, like any plan.
- Below the cap the rule is identical to today's (I = Dr_start + ETc,
  Dr_end = 0). Every case in cases.md is below the cap, checked by
  recomputation: largest need 28.75 mm against a 64 mm cap (cases 1, 3; 647
  min), 11.97 mm against 133 mm (case 2), 6.9 mm against 40 mm (task
  example). No number in cases.md changes.
- `need` is **not** capped at TAW *(builder's call, from the daily model)*:
  `need = Dr_start + ETc` is the water that ends the day full while the crop
  uses ETc during it, so it can exceed TAW by up to that day's ETc without
  holding water the soil can't hold. Only `Dr_end` is capped (I17); it reaches
  TAW only when the cap is below ETc (the crop is stressed and can't take
  more).
- The cap does not affect the suggestion (it never irrigates).
- The skill changes first (5.8), before any engine code.

**P11 case (new test, recomputed with a script):** North block, mid-season,
ET0 6.0, no rain, Kc 1.15 → ETc 6.9; TAW 122.5, RAW 49; cap 1440 min = 40 mm;
`bucket_start` 0.7 → Dr_0 36.75.

| Day | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bucket_mm | 78.85 | 111.95 | 122.50 | 115.60 | 108.70 | 101.80 | 94.90 |
| litres | 0 | 40000 | 17450 | 0 | 0 | 0 | 0 |
| run_minutes | 0 | 1440 | 628 | 0 | 0 | 0 | 0 |

Day 2 needs 50.55 mm (1819.8 min): 40 mm today, 10.55 mm left. Day 3:
10.55 + 6.9 = 17.45 mm (628.2 min), the bucket ends full.

**Rounding (I19, I20).** `Decimal(repr(round(x, 6))).quantize(Decimal("1"),
rounding=ROUND_HALF_UP)` for litres and minutes. Note: `cap_mm` comes out of
float as 39.99999999999999 in the P11 case; the 6-place step makes it 40000 L
and 1440 min.

### 5.8 Skill update (the first task of the plan)

The skill's own rules: decisions.md changes first, then SKILL.md, and SKILL.md
and cases.md change in the same commit (FR-2.11: every number as the skill
writes it). So the plan's first task, before any code, is one commit with:

- decisions.md: a new row I23 (P11, 5.7); the row "When and how much" amended
  ("refill to full, at most `MAX_DAILY_RUN_MINUTES` a day; the rest on the
  following days, I23").
- SKILL.md "The bucket": the I23 formula in place of the irrigate branch; the
  "Cap at TAW" bullet no longer says the cap only matters in the suggestion
  (I23 can reach it in a plan).
- SKILL.md "Bucket suggestion" and I18: "no suggestion" stays; the API form is
  `suggestion: null`, `reason: "season_ended"` (P3, P4), not a `stage` field
  in the suggestion response.
- cases.md: the P11 table of 5.7 as **case 5** (it is a hand-checked case of a
  formula in SKILL.md). Cases 1-4 unchanged.

### 5.9 Tests

Order: the engine first, with no HTTP.

1. **Engine, against cases.md, exact numbers:** cases 1-3 (every day's
   `bucket_mm`, `run_minutes`, the litres and minutes of the irrigation days,
   case 2's kc/Zr/TAW/RAW/ETc), case 4a/4b (suggestion), the task example
   (6900 L, 248 min).
2. **Deferred from stage 4.0:** (a) a suggestion where TAW grows (development
   stage) divides by today's TAW (I14); (b) rounding: `0.5005 * 1000` → 501
   (I19/I20).
3. **Q1-Q5:** the suggestion's single weather call (`days=1&past_days=92`,
   today from the answer, UTC+14 future check with weather down); the
   `WEATHER_REFRESH_DEADLINE_SECONDS` startup check; kc/mm rounding and
   pass-through of `et0_mm`/`rain_mm`; a `not_planted` day.
4. **I23:** the P11 table above (cases.md case 5 after 5.8); a capped day in a case where rain lands on
   the continuation day; the season ending during a continuation.
5. **Engine edges:** season end (P2 fields), I15 date edges (D = today,
   yesterday, today − 92, today − 93, before planting, future), I22 (fewer
   past days with and without reaching empty; 0 returned), the override
   (0 → daily ETc; 0.5 → the task's "half").
6. **Upstream/API with fakes** (`httpx.MockTransport`, no real service):
   404, 503 naming each service (connection error, timeout, 5xx), 500 for
   each kind of unexpected answer, stale forecast → every day `stale: true`,
   422 rules, P9, the parallel calls (plot first).
7. **Config:** strict keys, missing URL, non-finite values, P7 check, cap range.

### 5.10 README (service)

Run commands (from `services/planner-service`), settings table, both
endpoints with a JSON example, the error table, the I23 cap and why, the
stateless bucket and the suggestion flow, the 9 s worst case, a note that all
four seed seasons have ended and the demo creates a new plot with
`POST /v1/plots` (Q5), optional
Mermaid sequence diagram (frontend → planner → registry, then registry +
weather in parallel, and the failure branches).

## 6. Files

New: everything under `services/planner-service/` in 5.1 (except
`docs/research/fao56.md`, which exists). Later, in the plan stage, also:
`.claude/skills/irrigation-calc-reference/references/decisions.md` (I23) and
`SKILL.md` ("The bucket" formula, plus the `bell-pepper` ↔ "pepper" mapping),
and `docs/judgment-log.md` (entries 40-49, written with this design).

## 7. Judgment log entries

40 (P4), 41 (P6), 42 (P7), 43 (P11), 44 (Q1), 45 (Q2), 46 (Q3), 47 (Q4),
48 (Q5), 49 (order of checks in the suggestion).

## 8. Left to the builder

- Module boundaries inside `engine/`, names, dataclass shapes.
- Log lines (same logging setup as weather-service is the default).
- Test layout and fixture style.
- The README wording and diagram.

## 9. Decisions on Q1-Q5, and flags

All five approved by the owner (2026-11-18), option (a) each time. Not
re-opened.

- **Q1, decided: one weather call.** The suggestion calls weather once with
  `days=1&past_days=92`; "today" is the date after the past days. A future
  `last_irrigation` is validated before any call against UTC+14, like the
  registry. See 5.4.
- **Q2, decided: a planner key.** `WEATHER_REFRESH_DEADLINE_SECONDS=5` in
  `.env` (strict key, in `.env.example`); at startup
  `WEATHER_TIMEOUT_SECONDS` must exceed it. See 5.2.
- **Q3, decided: output precision.** `kc` 4 decimals, mm fields 2 decimals,
  half up (I19 rule); `et0_mm` and `rain_mm` exactly as weather sent them. See
  5.3.
- **Q4, decided: a day before planting.** `stage: "not_planted"`, zeros and
  nulls as in P2 (`kc`, `bucket_mm`, `bucket_capacity_mm` null). See 5.3.
- **Q5, decided: the seed stays.** All four seed seasons have ended. The
  README says so, and the demo creates a new plot with `POST /v1/plots`. See
  section 10.

**P9 (approved, 422 kept).** 422 says "your request is wrong", but the grower
can't fix a crop the planner has no coefficients for; it is a data/config gap.
The `detail` therefore says the crop has no coefficients and that this is a
data problem, not a request problem.

**P2 + Q5, requirement for stage 5.** An ended season returns
`run_minutes: 0` legitimately. The frontend must show "season ended", not "no
irrigation today". See section 10.

## 10. Requirements for later stages

- **Frontend (stage 5):**
  - Show "season ended" for `stage: "ended"` and for a suggestion with
    `reason: "season_ended"`, never "no irrigation today". Show a clear
    "not planted yet" for `stage: "not_planted"`.
  - Its planner timeout must be above 9 s (3 s registry + 6 s weather, worst
    case of one plan).
- **README (planner-service):** all four seed seasons have ended (planting
  dates 2026-02-15 to 2026-05-01, longest season 135 days), so seed plots plan
  `ended`; the demo creates a new plot with `POST /v1/plots`. The 9 s worst
  case. No in-memory state in the planner, so there is no one-worker
  constraint to note.
- **Skill (task I23):** add the `bell-pepper` ↔ "pepper" mapping (3).

## Appendix A. Owner decisions as given (2026-11-18)

- P1 day fields: required + `rain_mm`, `bucket_capacity_mm`, `stage` (per day).
- P2 after season end: stage `"ended"`, litres 0, run_minutes 0, kc null,
  bucket_mm null.
- P3 `GET /v1/plots/{id}/bucket-suggestion?last_irrigation=YYYY-MM-DD` ->
  `{plot_id, last_irrigation, suggestion (0-1 | null), exact, reason,
  past_days_requested, past_days_returned, stale}`. Rules: I14, I15, I18, I22.
- P4 "cannot suggest" -> 200 with suggestion null + reason
  (`"insufficient_past_weather"` | `"season_ended"`). Invalid input -> 422 (I15).
- P5 plan query `bucket_start` 0-1, default 1.0, else 422.
- P6 errors (problem+json, same format as registry/weather): registry 404 ->
  404 NOT_FOUND; upstream connection error/timeout/5xx -> 503
  UPSTREAM_UNAVAILABLE, detail names the service, Retry-After; any other
  unexpected upstream answer -> 500.
- P7 timeouts in .env: REGISTRY_TIMEOUT_SECONDS=3, WEATHER_TIMEOUT_SECONDS=6
  (must stay > weather's 5 s deadline, startup check).
- P8 no retries in the planner.
- P9 crop without coefficients -> 422 with a clear detail.
- P10 async httpx; plot first, then soil/emitter/crop + weather in parallel.
- P11 daily cap MAX_DAILY_RUN_MINUTES (default 1440, .env). If the refill
  needs more, irrigate the cap today and continue on the following days until
  the bucket is refilled. Added to the skill as I23.
