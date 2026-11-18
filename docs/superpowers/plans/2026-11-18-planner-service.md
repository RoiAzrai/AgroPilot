# planner-service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended here, see "Execution method") or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `services/planner-service` (port 8002) that answers "should I water this plot today, and for how many minutes?" with a 1-7 day plan and a bucket suggestion, every number from a pure engine that follows the skill exactly, and never a plan of zeros when an upstream fails.

**Architecture:** `engine/` is plain Python (dataclasses in, dataclasses out, no I/O, no clock, no settings object) and is built and tested first against cases.md. `upstream.py` fetches and strictly validates registry and weather answers (async httpx, `asyncio.timeout` around each whole call, no retries). `main.py` wires lifespan, routes and error mapping. The planner keeps no state.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, pydantic-settings, pytest (+ anyio plugin for async tests), uv.

**Spec:** `docs/superpowers/specs/2026-11-18-planner-service-design.md` (read it before any task; §n refers to its sections; all of P1-P11, Q1-Q5, judgment log 40-49 are DECIDED, do not re-open). Domain: `.claude/skills/irrigation-calc-reference/` (SKILL.md, references/cases.md, references/decisions.md) and `services/planner-service/docs/research/fao56.md`. Pattern to copy (never import): `services/weather-service` (`config.py`, `errors.py`, `main.py`, `tests/conftest.py`, `tests/fakes.py`).

## Global Constraints

- All commands from `services/planner-service` (`uv sync`, `uv run pytest`). Never import code from `registry-service` or `weather-service`; copy patterns.
- Each task touches **only** the files in its **ALLOWED FILES** block. Any other file: stop and ask.
- Tests never call the real registry, weather-service or Open-Meteo (fakes / `httpx.MockTransport` only). Tests never read a real `.env` (an autouse fixture points `config.ENV_FILE` at a non-existent path, as in weather-service). The agent never reads or writes `.env`.
- Engine purity: nothing under `engine/` imports `httpx`, `fastapi`, `config`, or reads a clock (`datetime.now`, `date.today`, `time`). "Today" and every date come from the weather answer.
- Every number is exactly as SKILL.md writes it (FR-2.11). No AI computes or adjusts a number. No hard-coded URLs, timeouts, cap, retries or soil water (`config.py` only).
- Rounding: litres and minutes whole, half up, `Decimal(repr(round(x, 6))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)` (I19/I20); served `kc` 4 decimals, `bucket_mm`/`bucket_capacity_mm` 2 decimals, half up; `et0_mm`/`rain_mm` pass through exactly as weather sent them (Q3).
- Crop table keyed by registry id: `tomato`, `bell-pepper` (the skill's "pepper").
- Settings (§5.2), strict keys (`extra="forbid"`, `allow_inf_nan=False`): `REGISTRY_URL` (req), `WEATHER_URL` (req), `REGISTRY_TIMEOUT_SECONDS=3`, `WEATHER_TIMEOUT_SECONDS=6`, `MAX_DAILY_RUN_MINUTES=1440` (1..1440), `DEPLETION_FRACTION_OVERRIDE` (unset, 0..1), `WEATHER_REFRESH_DEADLINE_SECONDS=5`, `RETRY_AFTER_SECONDS=5`. Startup: `WEATHER_TIMEOUT_SECONDS > WEATHER_REFRESH_DEADLINE_SECONDS`.
- Errors (§5.6): `application/problem+json` with exactly `type`, `title`, `status`, `detail`, `code`. 422 `VALIDATION`; 404 `NOT_FOUND`; 405 `VALIDATION`; 503 `UPSTREAM_UNAVAILABLE` + `Retry-After`, `detail` names `registry-service` or `weather-service`; 500 `INTERNAL` without details.
- Dependencies: `fastapi~=0.115`, `uvicorn~=0.32`, `httpx~=0.28`, `pydantic-settings~=2.6`; dev: `pytest~=9.2`. `[tool.uv] package = false`; pytest `pythonpath = ["."]`, `testpaths = ["tests"]`.
- Commit policy: **one commit per task**, only after that task's "Done when" holds. Message `planner-service: <what> (P2 4.3)` (Task 1: `skill: ...`), ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never commit `.env`, `registry.db`, `services/registry-service/perf/results/`.
- The skill files hold durable knowledge only: no to-do or pending-test lists in them (Task 1).

## Review Focus

The top risks, each pinned by a test in the owning task:

1. **Rounding** (I19/I20): `0.5005 * 1000` must give 501, `248.5` gives 249, `cap_mm` 39.99999999999999 gives 40000 L and 1440 min. Pinned: Task 3 `test_round_half_up_*`, `test_p11_cap_float_error`; Task 5 `test_kc_and_mm_served_half_up`.
2. **I23 continuation**: the cap day, the finishing day, rain on a continuation day, the season ending during a continuation, no change below the cap. Pinned: Task 4 `test_continuation_*`; Task 5 `test_case5_north_block_cap`, `test_rain_on_continuation_day`, `test_season_ends_during_continuation`.
3. **Upstream down gives 503, never zeros**: registry or weather down, slow or 5xx, including soil/emitter/crop calls, returns no `days` at all. Pinned: Task 9 `test_upstream_failure_never_a_plan`.
4. **Timeouts**: each whole call bounded by `asyncio.timeout` (a slow trickle that httpx per-phase timeouts would not catch); soil/emitter/crop/weather run in parallel. Pinned: Task 8 `test_whole_call_timeout_on_slow_body`, `test_parallel_calls`.
5. **Stale propagation**: weather `stale: true` gives every day `stale: true` and the top-level `stale`; the suggestion carries it too. Pinned: Task 9 `test_stale_forecast_marks_every_day`; Task 10 `test_suggestion_stale_propagates`.
6. **"Today" from the weather response, never the clock**: dates in the plan are weather's dates (a fake in 2031); the suggestion's today is the date after the past days; the engine has no clock. Pinned: Task 5 `test_engine_has_no_clock`; Task 9 `test_dates_come_from_weather`; Task 10 `test_today_is_date_after_past_days`.
7. **Order of checks in the suggestion** (§5.4): future date is a 422 even with the upstreams down; season-ended wins over date checks 4. Pinned: Task 10 `test_check_order_*`.

## Approved deviations

Approved by the owner before execution. Each one departs from the design; each is pinned by the test named.

- **(a) Suggestion does not fetch the emitter.** The suggestion never uses `flow_lph`, so the emitter call is skipped (design §5.5 lists it in the generic parallel set). An emitter outage cannot block a suggestion. Pinned: Task 10.
- **(b) `bucket_start` applies from the first planted day when day 1 is `not_planted`.** Before planting, TAW has no meaning, so `Dr_0 = (1 - bucket_start) * TAW` is set on the first planted day of the plan. Pinned: Task 5 `test_not_planted_day`; to be checked at STOP A.
- **(c) Weather down after the season has ended gives 503, not `season_ended`.** The suggestion needs "today" from weather before it can decide the season has ended (§5.4 step 3). Follows design Q1. Pinned: Task 10.

---

## Task 1: Skill update (one commit)

**Goal:** The skill says I23 and everything the engine will need before any code exists (§5.8).

**ALLOWED FILES:**
- Modify: `.claude/skills/irrigation-calc-reference/references/decisions.md`
- Modify: `.claude/skills/irrigation-calc-reference/SKILL.md`
- Modify: `.claude/skills/irrigation-calc-reference/references/cases.md`

**Recommended model:** Sonnet 5.5. Careful editing of three linked files with exact numbers; no design thinking, but a slip silently changes the spec the engine is tested against.

- [ ] **Step 1: Recompute case 5 independently.** In the scratchpad (not in the repo), script the §5.7 algorithm for the P11 case (loam 175, tomato mid, Zr 0.70, ET0 6.0, Kc 1.15, 1000 m², row 1.5, emitter 0.4, flow 1.0, cap 1440 min, `bucket_start` 0.7). Expected: bucket_mm `78.85 111.95 122.50 115.60 108.70 101.80 94.90`; litres `0 40000 17450 0 0 0 0`; run_minutes `0 1440 628 0 0 0 0`. Stop and report if the script disagrees with the design table.
- [ ] **Step 2: decisions.md.** Add row **I23 "Daily cap"** after the I22 row: `MAX_DAILY_RUN_MINUTES` (planner config, default 1440, range 1..1440); `cap_mm = MAX_DAILY_RUN_MINUTES * flow_lph / (row_spacing_m * emitter_spacing_m) / 60`; the refill is irrigated at most `cap_mm` a day and continues on the following days; the §5.7 rule (`refilling` flag, stop on the first day whose `Dr_start + ETc` fits under the cap, rain lowers the need, an `ended` day never irrigates, stateless: the continuation lives inside one plan, `need` is not capped at TAW and only `Dr_end` is, the suggestion is unaffected). Why: a day has 1440 minutes (North block needs about 1,800 for one refill). Deviation: beyond the task, which has no cap. Amend the **"When and how much"** row to "refill to full, at most `MAX_DAILY_RUN_MINUTES` a day, the rest on the following days (I23)". Amend the **I18** row so the API form is `suggestion: null`, `reason: "season_ended"` (not a `stage` field). Amend the last clause of the **I17** row ("Only the suggestion simulation reaches the cap...") because I23 can now reach it in a plan (not listed in §5.8; done only to avoid decisions.md contradicting itself; say so in the commit message).
- [ ] **Step 3: SKILL.md.** In "The bucket": replace the irrigate branch by the §5.7 pseudo-code (`cap_mm`, `refilling`, `need`, `I = min(need, cap_mm)`, `Dr_end = min(need - I, TAW)`) and reword the "Cap at TAW" bullet (I23 can reach it in a plan). Keep "Irrigate when the day would end below RAW" consistent with the new branch. In "Bucket suggestion" and its bullets: season ended gives `suggestion: null`, `reason: "season_ended"`. In the crop table notes add: the registry id of the second crop is `bell-pepper`, the engine keys it so.
- [ ] **Step 4: cases.md.** Add **Case 5: daily cap (I23)** after Case 4 and before the conversion check: input, plot, the §5.7 table, and the lines "Day 2 needs 50.55 mm (1819.8 min): 40 mm today, 10.55 mm left. Day 3: 10.55 + 6.9 = 17.45 mm (628.2 min), the bucket ends full." Cases 1-4 and the "Conversion check: the example in docs/task-p2.md" are not touched.
- [ ] **Step 5: Verify and commit.**
  Run: `git diff --stat` (exactly the 3 files), `git diff -U0 .claude/skills/irrigation-calc-reference/references/cases.md | grep '^-[^-]'` (no output: nothing removed).
  Commit: `git add` the 3 files; `git commit -m "skill: add I23 daily cap, case 5, bell-pepper mapping"`.

**Done when:** the three files changed in one commit; cases 1-4 and the lecturer example are byte-identical (no removed lines); case 5 numbers equal the recomputation; no to-do list in any skill file.

---

## Task 2: Scaffold, crop table, season functions

**Goal:** A uv project that runs `pytest`, plus the pure functions for season day, stage, Kc (Eq. 66) and root depth (Eq. 8-3).

**ALLOWED FILES:**
- Create: `services/planner-service/pyproject.toml`, `services/planner-service/uv.lock` (generated by `uv sync`)
- Create: `services/planner-service/engine/__init__.py`, `engine/crops.py`, `engine/season.py`
- Create: `services/planner-service/tests/test_season.py`

**Interfaces:**
- Produces (`engine/crops.py`): `@dataclass(frozen=True) class Crop: l_ini:int; l_dev:int; l_mid:int; l_late:int; kc_ini:float; kc_mid:float; kc_end:float; zmax:float; p:float` with property `season_length:int`; `CROPS: dict[str, Crop]` (`tomato` 30/40/40/25, Kc 0.60/1.15/0.80, Zmax 0.70, p 0.40; `bell-pepper` 30/35/40/20, Kc 0.60/1.05/0.90, Zmax 0.50, p 0.30); `class UnknownCrop(KeyError)`; `get_crop(crop_id: str) -> Crop` (raises `UnknownCrop`).
- Produces (`engine/season.py`): `season_day(day: date, planting_date: date) -> int` (planting day is 1); `stage(crop: Crop, i: int) -> str` (`not_planted` for `i < 1`, `ini`, `dev`, `mid`, `late`, `ended` for `i > season_length`); `kc(crop: Crop, i: int) -> float`; `root_depth(crop: Crop, i: int) -> float`.

- [ ] **Step 1: Write failing tests** in `tests/test_season.py`: `season_day(date(2026,3,2), date(2026,3,1)) == 2`; `season_day(planting, planting) == 1`; stage boundaries for tomato (`i=0 not_planted, 1 ini, 30 ini, 31 dev, 70 dev, 71 mid, 110 mid, 111 late, 135 late, 136 ended`); `kc(tomato, 80) == 1.15`; `kc(bell-pepper, 40) == pytest.approx(0.7286, abs=5e-5)` and `0.7800` at 44 (case 2 day 5: i=44, `abs=5e-5`); `kc(tomato, 135) == pytest.approx(0.80)`; `root_depth(bell-pepper, 40) == pytest.approx(0.38)`, `root_depth(bell-pepper, 41) == pytest.approx(0.3846, abs=5e-5)`; `root_depth(tomato, 80) == 0.70` (capped at `1`); `root_depth(tomato, 1) == 0.20`; `get_crop("bell-pepper")` works, `get_crop("pepper")` raises `UnknownCrop`.
- [ ] **Step 2: Run** `uv sync && uv run pytest tests/test_season.py -v`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** the files above. `pyproject.toml` as in Global Constraints (name `planner-service`, requires-python `>=3.12`). Formulas exactly SKILL.md "Kc (Eq. 66)" and "Root depth (Eq. 8-3)".
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: scaffold, crop table, season functions (P2 4.3)`.

**Done when:** `uv run pytest` is green from `services/planner-service`; `engine/` imports only the standard library.

---

## Task 3: drip.py (rounding, litres, minutes, cap)

**Goal:** The rounding rule and the drip conversion, with the float traps pinned.

**ALLOWED FILES:**
- Create: `services/planner-service/engine/drip.py`
- Create: `services/planner-service/tests/test_drip.py`

**Interfaces:**
- Produces: `round_half_up(x: float) -> int` (I19/I20 rule); `round_half_up_places(x: float, places: int) -> float` (same rule, for the served `kc` and mm fields); `cap_mm(max_daily_run_minutes: int, flow_lph: float, row_spacing_m: float, emitter_spacing_m: float) -> float`; `litres(irrigation_mm: float, area_m2: float) -> int`; `run_minutes(irrigation_mm: float, row_spacing_m: float, emitter_spacing_m: float, flow_lph: float) -> int` (from the unrounded `I`, area cancels, per SKILL.md).

- [ ] **Step 1: Write failing tests:**
  - `test_round_half_up_float_trap`: `round_half_up(0.5005 * 1000) == 501`.
  - `test_round_half_up_not_bankers`: `round_half_up(248.5) == 249`, `round_half_up(2.5) == 3`, `round_half_up(0.5) == 1`, `round_half_up(0.0) == 0`.
  - `test_round_half_up_places`: `round_half_up_places(2.675, 2) == 2.68`; `round_half_up_places(0.70315, 4) == 0.7032`.
  - `test_task_example`: `litres(6.9, 1000) == 6900`, `run_minutes(6.9, 1.5, 0.4, 1.0) == 248`.
  - `test_case1_day5`: `litres(28.75, 1000) == 28750`, `run_minutes(28.75, 1.5, 0.4, 1.6) == 647`.
  - `test_case2_day4`: `litres(11.9657, 400) == 4786`, `run_minutes(11.9657, 1.2, 0.3, 2.0) == 129`. (Use the unrounded I of case 2 day 4 if the engine test in Task 5 shows 11.9657 is rounded; here it is only the conversion.)
  - `test_case3_day7`: `litres(28.25, 1000) == 28250`, `run_minutes(28.25, 1.5, 0.4, 1.6) == 636`.
  - `test_p11_cap_float_error`: `cap_mm(1440, 1.0, 1.5, 0.4) == pytest.approx(40.0)`, `litres(cap_mm(1440, 1.0, 1.5, 0.4), 1000) == 40000`, `run_minutes(cap_mm(1440, 1.0, 1.5, 0.4), 1.5, 0.4, 1.0) == 1440`.
- [ ] **Step 2: Run** `uv run pytest tests/test_drip.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/drip.py`. `round_half_up` as the I19 note (round to 6 places, then `Decimal(repr(...))`, `ROUND_HALF_UP`); the 6 is a named module constant.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: drip conversion and half-up rounding (P2 4.3)`.

**Done when:** all tests green, including the float traps.

**Recommended model:** Sonnet 5.5. The signatures and tests pin everything, but the rounding trap is easy to get subtly wrong and costs a wrong number silently.

---

## Task 4: bucket.py (TAW/RAW/ETc, the daily step, I23)

**Goal:** One day's bucket step, with the cap and the continuation flag, as one pure function.

**ALLOWED FILES:**
- Create: `services/planner-service/engine/bucket.py`
- Create: `services/planner-service/tests/test_bucket.py`

**Interfaces:**
- Consumes: nothing from Task 3 (cap is passed in as `cap_mm`).
- Produces: `taw(available_water_mm_per_m: float, zr: float) -> float`; `raw(p: float, taw_mm: float) -> float`; `effective_rain(rain_mm: float, et0_mm: float) -> float` (`rain if rain >= 0.2 * et0 else 0`); `@dataclass(frozen=True) class StepResult: irrigation_mm: float; dr_end: float; refilling: bool`; `step(dr_prev: float, rain_mm: float, et0_mm: float, etc_mm: float, taw_mm: float, raw_mm: float, cap_mm: float, refilling: bool) -> StepResult` implementing SKILL.md "The bucket" as amended by Task 1 (§5.7 pseudo-code).

- [ ] **Step 1: Write failing tests** (TAW 122.5, RAW 49, ET0 6.0, ETc 6.9, cap 40 unless noted):
  - `test_rain_filter`: `effective_rain(0.5, 5.0) == 0`; `effective_rain(1.0, 5.0) == 1.0` (boundary `>=`).
  - `test_no_irrigation_below_raw`: `step(36.75, 0, 6.0, 6.9, ..., False)` gives `irrigation_mm == 0`, `dr_end == pytest.approx(43.65)`, `refilling is False`.
  - `test_capped_day`: `step(43.65, ...)` gives `irrigation_mm == 40`, `dr_end == pytest.approx(10.55)`, `refilling is True`.
  - `test_continuation_finishing_day`: `step(10.55, ..., refilling=True)` gives `irrigation_mm == pytest.approx(17.45)`, `dr_end == 0`, `refilling is False`.
  - `test_continuation_forces_irrigation_below_raw`: with `refilling=True` the finishing day irrigates although `Dr_start + ETc` (17.45) is below RAW 49.
  - `test_continuation_rain_lowers_need`: `step(10.55, 12.0, 6.0, 6.9, ..., True)` gives `irrigation_mm == pytest.approx(6.9)`, `dr_end == 0`.
  - `test_below_cap_identical_to_old_rule`: case 1 day 5 (`dr_prev 17.25`, ETc 5.75, TAW 58.10, RAW 23.24, cap 64): `irrigation_mm == pytest.approx(28.75)`, `dr_end == 0`, `refilling is False`.
  - `test_dr_end_capped_at_taw`: cap 1 mm, `dr_prev 120`, ETc 6.9, TAW 122.5: `dr_end == 122.5`, `refilling is True` (I17, crop stressed).
  - `test_rain_beyond_full`: `dr_prev 3`, rain 12 (ET0 6): `dr_start` clamps to 0 (`dr_end == pytest.approx(6.9)` with no irrigation).
- [ ] **Step 2: Run** `uv run pytest tests/test_bucket.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/bucket.py`. The cap math is the §5.7 pseudo-code: `need = Dr_start + ETc`, `I = min(need, cap_mm)`, `Dr_end = min(need - I, TAW)`, `refilling = Dr_end > 0`; irrigate when `refilling or need > RAW`. `need` is not capped at TAW.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: daily bucket step with I23 cap (P2 4.3)`.

**Done when:** all tests green; the below-cap test shows the old rule is unchanged.

**Recommended model:** Sonnet 5.5. A short function, but the continuation flag logic is the subtle part of the design and the tests are exact; no need for Opus because the pseudo-code is given.

---

## Task 5: plan.py (a whole plan, cases 1-3 and 5, not_planted, ended)

**Goal:** `build_plan` assembles the day-by-day plan from the pieces, with the served rounding, and reproduces every hand-calculated case exactly.

**ALLOWED FILES:**
- Create: `services/planner-service/engine/plan.py`
- Create: `services/planner-service/tests/test_plan.py`

**Interfaces:**
- Consumes: Tasks 2-4 (`get_crop`, `season_day`, `stage`, `kc`, `root_depth`, `taw`, `raw`, `effective_rain`, `step`, `cap_mm`, `litres`, `run_minutes`, `round_half_up_places`).
- Produces: `@dataclass(frozen=True) class PlotInputs: crop_id: str; planting_date: date; area_m2: float; row_spacing_m: float; emitter_spacing_m: float; flow_lph: float; available_water_mm_per_m: float`; `@dataclass(frozen=True) class DayWeather: date: date; et0_mm: float; rain_mm: float`; `@dataclass(frozen=True) class PlanDay: date: date; stage: str; et0_mm: float; rain_mm: float; kc: float | None; litres: int; run_minutes: int; bucket_mm: float | None; bucket_capacity_mm: float | None`; `build_plan(plot: PlotInputs, weather: Sequence[DayWeather], bucket_start: float, max_daily_run_minutes: int, depletion_fraction_override: float | None) -> list[PlanDay]` (raises `UnknownCrop`). `p` is the crop's, or the override when set (I21).
- Rules to implement: `Dr_0 = (1 - bucket_start) * TAW` of the **first planted day of the plan**; `not_planted` and `ended` days have `litres 0`, `run_minutes 0`, `kc/bucket_mm/bucket_capacity_mm None` and keep the forecast's `et0_mm`/`rain_mm`; an `ended` day ends any continuation; `Dr` carries over in mm while TAW changes (cap at TAW of the day); `bucket_mm = TAW - Dr_end`; the served values are rounded at the end (`kc` 4, mm fields 2), the internal chain stays unrounded.

- [ ] **Step 1: Write failing tests.** Helper `plan_for(...)` builds `PlotInputs` with `planting_date = day1 - (season_day - 1) days`.
  - `test_case1`: bucket_mm `[52.35, 46.60, 40.85, 35.10, 58.10, 52.35, 46.60]`, run_minutes `[0,0,0,0,647,0,0]`, day 5 litres 28750.
  - `test_case2`: pepper, sand 83, day 1 = season day 40, ET0 4.0, area 400, row 1.2, em 0.3, flow 2.0: kc `[0.7286, 0.7414, 0.7543, 0.7671, 0.78, 0.7929, 0.8057]`, bucket_capacity_mm `[31.54, 31.92, 32.31, 32.69, 33.07, 33.46, 33.84]`, bucket_mm `[28.63, 26.04, 23.41, 32.69, 29.95, 27.16, 24.32]`, day 4 litres 4786, run_minutes 129. (Case 2's table shows 3 decimals; compare with `abs=0.006`, and assert the day-4 irrigation day exactly.)
  - `test_case3_rain`: case 1 plus rain 0.5 on day 2 and 12 on day 4: bucket_mm `[52.35, 46.60, 40.85, 47.10, 41.35, 35.60, 58.10]`, run_minutes `[0,0,0,0,0,0,636]`, day 7 litres 28250.
  - `test_task_example_and_override_zero`: tomato mid, 1000 m², ET0 6.0, no rain, row 1.5, em 0.4, flow 1.0, `bucket_start 1.0`, `depletion_fraction_override=0` (I21, daily irrigation of ETc): every day `litres == 6900`, `run_minutes == 248`, `bucket_mm == bucket_capacity_mm`.
  - `test_override_half`: `override 0.5` triggers irrigation at half of TAW (task's "half"), compared with default p.
  - `test_case5_north_block_cap`: loam 175, tomato mid (Zr 0.70, TAW 122.5), ET0 6.0, 1000 m², row 1.5, em 0.4, flow 1.0, `bucket_start 0.7`, cap 1440: bucket_mm `[78.85, 111.95, 122.50, 115.60, 108.70, 101.80, 94.90]`, litres `[0, 40000, 17450, 0, 0, 0, 0]`, run_minutes `[0, 1440, 628, 0, 0, 0, 0]`.
  - `test_rain_on_continuation_day`: case 5 with rain 12 on day 3: day 3 litres 6900, run_minutes 248, bucket_mm 122.5; day 4 bucket_mm 115.6.
  - `test_season_ends_during_continuation`: tomato with day 1 = season day 135, `bucket_start 0`, `max_daily_run_minutes 60`: day 1 `run_minutes == 60` (capped, stage `late`); day 2 stage `ended`, `litres 0`, `run_minutes 0`, `kc None`, `bucket_mm None`, `bucket_capacity_mm None`, `et0_mm`/`rain_mm` equal the input.
  - `test_not_planted_day`: day 1 before planting: P2-style zeros/nulls, `stage "not_planted"`, and the next day (season day 1) uses `bucket_start` on its own TAW.
  - `test_kc_and_mm_served_half_up`: a day whose unrounded `bucket_mm` ends in `...005` is served half up (build the input so TAW ends in 5 at the third decimal, or unit-test the final rounding helper used inside `build_plan`).
  - `test_et0_rain_pass_through`: `et0_mm=4.123456`, `rain_mm=0.987654` come back identical.
  - `test_unknown_crop`: `build_plan(... crop_id="wheat" ...)` raises `UnknownCrop`.
  - `test_engine_has_no_clock`: read every `engine/*.py` and assert none contains `now(`, `today(`, `import time`, `httpx`, `fastapi`, `config`.
- [ ] **Step 2: Run** `uv run pytest tests/test_plan.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/plan.py` per the rules above.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS (all of cases 1, 2, 3, 5 and the task example exact).
- [ ] **Step 5: Commit** `planner-service: plan engine, cases 1-3, 5 and task example (P2 4.3)`.

**Done when:** every cases.md case (1, 2, 3, 5), the lecturer example, I21 and the stage edges pass with the exact numbers above; the clock test is green.

**Recommended model:** Sonnet 5.5. Largest engine task, but every value is pinned; needs care, not deep design. (Task 5 is where a downgrade to Haiku would be a false economy.)

---

## Task 6: suggestion.py (I14-I18, I22)

**Goal:** The bucket suggestion and the date rules, pure, with fewer-past-days handling.

**ALLOWED FILES:**
- Create: `services/planner-service/engine/suggestion.py`
- Create: `services/planner-service/tests/test_suggestion.py`

**Interfaces:**
- Consumes: `DayWeather` (Task 5), `get_crop`, `season_day`, `kc`, `root_depth`, `effective_rain`, `taw`, `round_half_up_places`.
- Produces: `class InvalidLastIrrigation(ValueError)`; `MAX_PAST_DAYS = 92`; `past_days_requested(last_irrigation: date, today: date) -> int` (`max(today - last_irrigation - 1 days, 0)`, I22); `check_last_irrigation(last_irrigation: date, today: date, planting_date: date) -> None` (raises for: after `today`, before `planting_date`, `today - last_irrigation > 92 days`; `last_irrigation == today - 92` is valid, `today - 93` is not); `@dataclass(frozen=True) class Suggestion: value: float | None; exact: bool; reason: str | None; past_days_requested: int; past_days_returned: int`; `suggest(crop_id: str, planting_date: date, available_water_mm_per_m: float, last_irrigation: date, today: date, past_weather: Sequence[DayWeather]) -> Suggestion` where `past_weather` are the past days weather returned for D+1..yesterday, ascending (empty when none are needed). Value rounded to 4 decimals half up. Reasons: `"insufficient_past_weather"`.
- Rules: D = today or yesterday gives `1.0`, `exact True`, 0/0; all requested days returned gives the SKILL.md simulation (no irrigation, rain filter I16, cap at TAW of that day I17), `suggestion = clamp(1 - Dr / TAW(today), 0, 1)` (I14); fewer returned (at least 1): start full at the **start** of the first returned day, `exact True` only if the run reaches empty on any day, else `value None`, `exact False`, `reason "insufficient_past_weather"`; 0 returned with D < yesterday: the same "cannot suggest". Season ended is decided by the caller (`stage(...) == "ended"`), not here.

- [ ] **Step 1: Write failing tests:**
  - `test_case_4a`: tomato, sand 83, today = season day 80, ET0 5.0, no rain, D = day 76, past days 77, 78, 79: `value == 0.7031`, `exact True`, requested 3, returned 3.
  - `test_case_4b`: D = day 65, 14 past days (66..79): `value == 0.0`, `exact True`.
  - `test_taw_grows_uses_todays_taw` (I14): tomato, sand 83, today = season day 40 (dev), D = day 36, past days 37-39, ET0 5.0: `value == 0.7319` (Dr 10.65 over TAW(day 40) 39.7214; dividing by TAW(day 39) would give 0.7278).
  - `test_d_today_and_yesterday`: both give `1.0`, requested 0, returned 0.
  - `test_fewer_days_not_reaching_empty`: D = day 65, requested 14, only the last 3 returned: `value None`, `exact False`, `reason "insufficient_past_weather"`, returned 3.
  - `test_fewer_days_reaching_empty`: same D, 12 returned (days 68..79): `value == 0.0`, `exact True`.
  - `test_zero_returned`: D < yesterday, empty `past_weather`: `value None`, `reason "insufficient_past_weather"`, returned 0.
  - `test_rain_in_past_days`: a past day with rain 1.0 and ET0 5.0 (>= 0.2 x ET0) lowers Dr; rain 0.5 is ignored (I16).
  - `test_check_last_irrigation_edges`: valid: today, yesterday, `today - 92`, the planting date; raises: `today + 1`, `today - 93`, planting date minus 1.
  - `test_past_days_requested`: `(D=today-5) -> 4`, `(today) -> 0`, `(yesterday) -> 0`.
- [ ] **Step 2: Run** `uv run pytest tests/test_suggestion.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/suggestion.py`.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: bucket suggestion engine (P2 4.3)`.

**Done when:** cases 4a/4b, the TAW-growth test and every I15/I22 edge pass.

**Recommended model:** Sonnet 5.5. The optimistic-bound logic (I22) is the most subtle engine piece, but it is fully specified and the tests pin it; Opus is not needed unless the executor fails the two I22 tests twice.

---

## >>> STOP A: engine review (joint)

Stop after Task 6. Nothing HTTP exists yet. Review together: `uv run pytest -v` output; the diff of Tasks 1-6; each Review Focus item 1, 2 and 6 (engine part) against its test; the cases.md numbers against the tests. Do not start Task 7 until the owner says go. Open points to confirm at this stop: the first-planted-day rule for `bucket_start` (see "Unsure"), and the I17 row edit in Task 1.

---

## Task 7: config.py and .env.example

**Goal:** Strict settings that stop the service at startup on anything wrong.

**ALLOWED FILES:**
- Create: `services/planner-service/config.py`, `services/planner-service/.env.example`
- Create: `services/planner-service/tests/conftest.py`, `services/planner-service/tests/test_config.py`

**Interfaces:**
- Produces: `ENV_FILE: Path`; `class Settings(BaseSettings)` with the §5.2 keys as lower-case fields (`registry_url: str`, `weather_url: str`, `registry_timeout_seconds: float = 3`, `weather_timeout_seconds: float = 6`, `max_daily_run_minutes: int = 1440`, `depletion_fraction_override: float | None = None`, `weather_refresh_deadline_seconds: float = 5`, `retry_after_seconds: int = 5`); `get_settings() -> Settings` raising `RuntimeError` with a clear message. Copy the shape of weather-service `config.py`.
- `tests/conftest.py`: autouse fixture that sets `REGISTRY_URL`/`WEATHER_URL` env vars to `.invalid` hosts and monkeypatches `config.ENV_FILE` to a non-existent tmp path.

- [ ] **Step 1: Write failing tests** (`test_config.py`): defaults; missing or blank `REGISTRY_URL`/`WEATHER_URL` raise naming the key; unknown key in an env file raises (`extra="forbid"`, test through a tmp `.env`-style file written by the test, never the real one); parametrized `inf`/`nan`/`-1`/`0` for every timeout key; `WEATHER_TIMEOUT_SECONDS == WEATHER_REFRESH_DEADLINE_SECONDS` and below it raise (message names both keys); `6` above `5` passes; `MAX_DAILY_RUN_MINUTES` `0` and `1441` raise, `1` and `1440` pass; `DEPLETION_FRACTION_OVERRIDE` `-0.1`, `1.1`, `nan` raise, `0` and `1` pass, unset gives `None`; `.env.example` contains every key (the test parses the file's key names and compares to `Settings.model_fields` upper-cased) and no real secret/URL beyond `127.0.0.1` examples.
- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `config.py` and `.env.example` (placeholders only: `REGISTRY_URL=http://127.0.0.1:8000`, `WEATHER_URL=http://127.0.0.1:8001`, defaults for the rest with a one-line comment each).
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: strict settings and .env.example (P2 4.3)`.

**Done when:** every bad value from §5.2 fails fast with a readable message; no test reads a real `.env`.

**Recommended model:** Sonnet 5.5. Mechanical copy of a known pattern, but the cross-field check and the `inf`/`nan` handling need attention.

---

## Task 8: upstream.py (async clients, timeouts, validation)

**Goal:** The only module that talks HTTP; every answer strictly validated; failures typed.

**ALLOWED FILES:**
- Create: `services/planner-service/upstream.py`
- Create: `services/planner-service/tests/fakes.py`, `services/planner-service/tests/test_upstream.py`

**Interfaces:**
- Consumes: `Settings` (Task 7), `PlotInputs`/`DayWeather` (Task 5).
- Produces: exceptions `class UpstreamUnavailable(Exception)` (fields `service: str` of `"registry-service"` / `"weather-service"`, `retry_after: int | None`), `class PlotNotFound(Exception)`, `class UnexpectedUpstream(Exception)`; `@dataclass(frozen=True) class PlotRecord` (the registry fields of §5.5: `area_m2, crop_id, planting_date, soil_id, row_spacing_m, emitter_spacing_m, emitter_id, lat, lon`); `@dataclass(frozen=True) class Forecast: days: list[DayWeather]; past_days_returned: int; fetched_at: str; stale: bool`; `class Upstream` built with `(client: httpx.AsyncClient, settings: Settings)` and async methods `get_plot(plot_id: str) -> PlotRecord`, `get_soil_water(soil_id: str) -> float`, `get_flow_lph(emitter_id: str) -> float`, `check_crop(crop_id: str) -> None`, `get_forecast(lat: float, lon: float, days: int, past_days: int = 0) -> Forecast`. Each call runs inside `asyncio.timeout(registry or weather timeout)` and makes exactly one request (no retries).
- Mapping: connection error, `asyncio.TimeoutError`, 5xx become `UpstreamUnavailable` (weather: `retry_after` from its `Retry-After` header when it is a positive integer); plot 404 becomes `PlotNotFound`; any other 4xx, bad JSON, missing/ wrong-typed field, non-finite or non-positive registry number, a 404 on soil/emitter/crop, weather with the wrong number of days (`days + past_days_returned`), non-consecutive dates, non-finite or negative `et0_mm`/`rain_mm`, `past_days_returned` outside `0..past_days` all become `UnexpectedUpstream`. Never fills a missing number.
- `tests/fakes.py`: a small registry+weather `httpx.MockTransport` builder (routes `/v1/plots/{id}`, `/v1/soils/{id}`, `/v1/emitters/{id}`, `/v1/crops/{id}`, `/v1/forecast`), recording requests, with per-route overrides (status, body, delay, raised exception).

- [ ] **Step 1: Write failing tests:**
  - `test_happy_path_parses_plot_soil_emitter_forecast` (field values equal the fake's).
  - `test_whole_call_timeout_on_slow_body`: a fake that streams the body slowly past a 0.05 s registry timeout gives `UpstreamUnavailable(service="registry-service")` (a trickle that per-phase httpx timeouts would miss).
  - `test_weather_timeout_names_weather_service`.
  - `test_5xx_and_connect_error_unavailable` (both services; the registry's soil, emitter and crop calls too, naming `registry-service`).
  - `test_weather_retry_after_passed_on`: header `7` gives `retry_after == 7`; missing/garbage gives `None`.
  - `test_plot_404_is_plot_not_found`; `test_soil_emitter_crop_404_is_unexpected`.
  - `test_unexpected_answers` parametrized: invalid JSON, JSON array, missing field, string where number, `area_m2` 0/-1/`NaN`, other 4xx (400, 422), weather one day short, duplicate/gapped dates, `et0_mm` null/-0.1/NaN, `rain_mm` missing, `past_days_returned` greater than asked.
  - `test_no_retries`: a 503 is requested exactly once.
  - `test_parallel_calls`: with a barrier (`asyncio.Event`) that releases only when soil, emitter, crop and weather are all in flight, a gather of the four completes; and `get_plot` is requested before any of them (order recorded).
  - `test_forecast_query`: `get_forecast(lat, lon, 1, 92)` sends `days=1&past_days=92` once.
- [ ] **Step 2: Run** `uv run pytest tests/test_upstream.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `upstream.py` (strict parsing with explicit type checks: `bool` is not a number; `math.isfinite`).
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: upstream clients with whole-call timeouts (P2 4.3)`.

**Done when:** every row of the §5.6 upstream-failure mapping has a test, and no test uses a real socket.

**Recommended model:** Sonnet 5.5. Async, timeouts and a table of failure mappings; many cases but each is stated.

---

## Task 9: errors.py, models.py, main.py: the plan endpoint

**Goal:** `GET /v1/plots/{id}/plan` end to end over fakes, with problem+json errors.

**ALLOWED FILES:**
- Create: `services/planner-service/errors.py`, `services/planner-service/models.py`, `services/planner-service/main.py`
- Modify: `services/planner-service/tests/conftest.py` (add `client` fixture and `assert_problem` helper only), `services/planner-service/tests/fakes.py` (only to add what the API tests need)
- Create: `services/planner-service/tests/test_api_plan.py`

**Interfaces:**
- Consumes: Tasks 5, 7, 8.
- Produces: `app` with a lifespan that creates one `httpx.AsyncClient` and an `Upstream` (injectable transport for tests, as in weather-service `main.py`); `GET /health`; `GET /v1/plots/{plot_id}/plan?days=1..7 (default 7)&bucket_start=0..1 (default 1.0, finite)`; `utc_now()` is NOT needed here (dates come from weather). `errors.py`: `AppError(status, code, detail, headers=None)` and handlers for `AppError`, `RequestValidationError`, `StarletteHTTPException` (404 `NOT_FOUND`, 405 `VALIDATION`), `UpstreamUnavailable` (503 `UPSTREAM_UNAVAILABLE`, `detail "<service> is unavailable"`, `Retry-After` = upstream's or `RETRY_AFTER_SECONDS`), `PlotNotFound` (404 `NOT_FOUND`), `UnknownCrop` (422 `VALIDATION`, detail: no coefficients, a data problem not a request problem), `UnexpectedUpstream` and any `Exception` (500 `INTERNAL`, no details). `models.py`: response models of §5.3 (top-level `plot_id, crop, bucket_start, fetched_at, stale, days`; each day `date, stage, et0_mm, rain_mm, kc, litres, run_minutes, bucket_mm, bucket_capacity_mm, stale`).
- Flow: plot first; then soil, emitter, crop check and forecast (`days`) in parallel via `asyncio.gather`; `build_plan(..., max_daily_run_minutes=settings.max_daily_run_minutes, depletion_fraction_override=settings.depletion_fraction_override)`; every day's `stale` and the top-level `stale` come from the forecast; the first failure noticed names the service.

- [ ] **Step 1: Write failing tests** (`test_api_plan.py`, TestClient + fake transport):
  - `test_plan_200_shape`: top-level keys exactly as §5.3; day keys exactly the 10 fields; values for a case-1-like plot equal the engine numbers (e.g. 7 days, day 5 `run_minutes 647`).
  - `test_dates_come_from_weather`: the fake forecast starts on `2031-03-01`; `days[0].date == "2031-03-01"` and the number of days equals what weather returned.
  - `test_stale_forecast_marks_every_day`: weather `stale: true` gives top-level `stale true`, each day `stale true`, `fetched_at` passed through.
  - `test_422_days_and_bucket_start`: `days=0`, `8`, `x`; `bucket_start=-0.1`, `1.1`, `nan`, `inf`, `x`; each `assert_problem(..., 422, "VALIDATION")`, no upstream call recorded.
  - `test_defaults_days_7_bucket_start_1`.
  - `test_plot_404_is_404_not_found`; `test_unknown_route_404`, `test_wrong_method_405_validation`.
  - `test_upstream_failure_never_a_plan`: parametrized over registry plot / soil / emitter / crop, and weather: connection error, timeout, 500, 503 with `Retry-After: 9`; each gives 503 `UPSTREAM_UNAVAILABLE`, `detail` names the right service, `Retry-After` present (9 for weather's header, else `RETRY_AFTER_SECONDS`), and the body has **no** `days` key (never a plan of zeros).
  - `test_unexpected_upstream_is_500_internal_without_details` (bad JSON from weather, wrong day count, soil 404): body has no upstream text.
  - `test_unknown_crop_is_422_with_data_problem_detail` (registry crop `wheat`).
  - `test_ended_season_plan` (seed-like plot, planting 2026-02-15 and weather days in 2026-11): every day `stage "ended"`, zeros/nulls per P2, `et0_mm`/`rain_mm` from weather.
  - `test_problem_json_content_type_and_exact_keys` (via `assert_problem`).
  - `test_p11_cap_through_http`: the North-block plot returns 1440 min and 40000 L on day 2 with `MAX_DAILY_RUN_MINUTES` default.
- [ ] **Step 2: Run** `uv run pytest tests/test_api_plan.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the three modules. Copy `errors.py` shape from weather-service; log lines per its logging setup; no upstream text in any body.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `planner-service: plan endpoint and error mapping (P2 4.3)`.

**Done when:** every error in §5.6 for the plan endpoint has a test; no 503 or 500 body contains a plan.

**Recommended model:** Sonnet 5.5. Wiring work with many small exact assertions; the tricky part (never zeros) is covered by the parametrized test.

---

## Task 10: bucket-suggestion endpoint and the check order

**Goal:** `GET /v1/plots/{id}/bucket-suggestion?last_irrigation=YYYY-MM-DD` with the fixed order of checks (§5.4).

**ALLOWED FILES:**
- Modify: `services/planner-service/main.py`, `services/planner-service/models.py`
- Modify: `services/planner-service/tests/fakes.py` (only if needed)
- Create: `services/planner-service/tests/test_api_suggestion.py`

**Interfaces:**
- Consumes: Tasks 6, 8, 9.
- Produces: the route; `utc_now() -> datetime` in `main.py` (monkeypatchable; the only clock in the service, used only for the UTC+14 future check of step 1); response model `{plot_id, last_irrigation, suggestion, exact, reason, past_days_requested, past_days_returned, stale}`.
- Order: **(1)** `last_irrigation` unparsable, or later than `(utc_now() + 14h).date()`: 422 before any upstream call. **(2)** fetch the plot (404/503). Then soil, crop check and one weather call `days=1&past_days=92` in parallel (the emitter is not fetched: the suggestion never uses it; see "Unsure"). `today = forecast.days[past_days_returned].date`. **(3)** season ended on `today`: 200 `suggestion null, exact false, reason "season_ended"`, 0/0 days. **(4)** `check_last_irrigation(...)` failing (before planting, more than 92 days back, after the point's today): 422. **(5)** `suggest(...)` with `past_weather = past days[-requested:]` (the last `past_days_requested` returned), `stale` from the forecast.

- [ ] **Step 1: Write failing tests:**
  - `test_check_order_future_date_422_even_when_upstreams_down`: both fakes raise connection errors, `last_irrigation = utc_now + 3 days`: 422, zero upstream requests recorded.
  - `test_check_order_invalid_format_422_before_upstream` (`2026-13-40`, `abc`, empty).
  - `test_check_order_unknown_plot_404_with_valid_date`; registry down gives 503 naming `registry-service`; weather down gives 503 naming `weather-service` (never `suggestion` zeros).
  - `test_check_order_season_ended_wins`: ended plot and `last_irrigation` before the planting date: 200, `suggestion null`, `reason "season_ended"`, `exact false`.
  - `test_422_before_planting_more_than_92_back_and_after_point_today` (passes step 1 via the UTC+14 margin, fails step 4 against weather's today).
  - `test_today_is_date_after_past_days`: fake weather returns 3 past days and 1 today starting `2031-03-01`; `today` is the 4th date and `past_days_requested` follows from it; the request sent to weather was `days=1&past_days=92` exactly once.
  - `test_d_yesterday_and_today_give_1_0_with_0_0_days`.
  - `test_case_4a_through_http`: `suggestion 0.7031, exact true, past_days_requested 3, past_days_returned 3`.
  - `test_fewer_past_days_returned`: reaches empty gives exact with value; does not reach gives `suggestion null`, `reason "insufficient_past_weather"`, `past_days_returned` equals what weather had.
  - `test_suggestion_stale_propagates`: weather `stale true` gives response `stale true`.
- [ ] **Step 2: Run** `uv run pytest tests/test_api_suggestion.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the route.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `planner-service: bucket-suggestion endpoint and check order (P2 4.3)`.

**Done when:** each of the five ordered checks has a test, and the suggestion makes exactly one weather call.

**Recommended model:** Sonnet 5.5. Ordering rules and a clock edge, all exact in the design; Opus is not needed.

---

## >>> STOP B: API review (joint)

Stop after Task 10. Review together: full `uv run pytest -v`; Review Focus items 3, 4, 5, 6, 7 against their tests; the problem+json bodies; the 9 s worst-case arithmetic (3 s + 6 s). Then the owner does the manual smoke test (below) before Task 11 is written against real behavior.

---

## Task 11: README

**Goal:** The service README the task asks for.

**ALLOWED FILES:**
- Create: `services/planner-service/README.md`

**Interfaces:** none (docs).

- [ ] **Step 1: Write** the README per §5.10: run commands (from `services/planner-service`), the settings table (§5.2), both endpoints with a JSON example each (the §5.3 and §5.4 bodies), the error table (§5.6), the I23 cap and why (North block needs about 1,800 min), the stateless bucket and the suggestion flow, the 9 s worst case (the frontend's timeout must be above it), a note that **all four seed seasons have ended** (planting 2026-02-15 to 2026-05-01, longest season 135 days) so seed plots plan `ended`, and the demo creates a new plot with `POST /v1/plots`; optional Mermaid sequence diagram (frontend, planner, registry, then registry and weather in parallel, failure branches).
- [ ] **Step 2: Check** that every number in the JSON examples is consistent with the engine (copy from a real test run, not by hand) and every setting name matches `.env.example`. Run `uv run pytest -v` (still green; README changes no code).
- [ ] **Step 3: Commit** `planner-service: README (P2 4.3)`.

**Done when:** the README example JSON equals a real response shape (keys exactly), and the seed-seasons-ended note is there.

**Recommended model:** Haiku 5.5. Docs only, copied from the design and real test output.

---

## Manual steps for the user

What the user does (the agent never does these):

1. After Task 7, **create `services/planner-service/.env` yourself** from `.env.example` (`cp .env.example .env`, then set the URLs if different). The agent never reads, writes or prints `.env`.
2. At STOP B, run the three services in three terminals (each from its own folder): `uv run uvicorn main:app --port 8000` (registry), `--port 8001` (weather), `--port 8002` (planner).
3. Create a fresh plot with a current planting date: `POST http://127.0.0.1:8000/v1/plots` (seed plots have ended seasons).
4. Try `GET http://127.0.0.1:8002/v1/plots/{id}/plan`, `.../plan?days=3&bucket_start=0.7`, and `.../bucket-suggestion?last_irrigation=<a few days ago>`.
5. Stop the weather service and repeat: expect 503 `UPSTREAM_UNAVAILABLE` naming `weather-service`, never a plan.
6. Decide about merging/PR (the agent does not push or merge).

What the agent never does: read or write any `.env`; touch `registry.db`, the PostgreSQL `registry` database or `perf/results/`; call the real registry, weather-service or Open-Meteo from tests; edit files outside a task's ALLOWED FILES; commit before a task's "Done when" holds.

## Execution method

**Chosen method: inline (superpowers:executing-plans), one session on `p2`, switching model per task, with the joint reviews at STOP A and STOP B.**

- Run each task inline, but run `/clear` between tasks to keep the context small.
- Each task starts from this plan file, not from the previous task's conversation. The file holds the interfaces, the tests and the "Done when" criteria the task needs.
- The independent reviewer subagent runs only at STOP B (Tasks 8-10, the async/timeouts code, where a mistake would be an outage rather than a wrong number). It does not run per task.

Reasons: Tasks 2-6 share small interfaces (`Crop`, `DayWeather`, `StepResult`) that a fresh subagent per task would have to re-read cold; there are 11 small tasks; and a subagent per task plus a reviewer per task costs more tokens than the owner's two joint reviews.

**Commit-per-task policy:** exactly one commit per task, made only after the task's tests and "Done when" pass, `git add` of that task's ALLOWED FILES by name (never `git add -A`), message as in Global Constraints. If a step forces a file outside ALLOWED FILES, stop and ask. Task 1 is the only commit that touches `.claude/skills/`.

## Unsure (flagged for the owner, not decided by this plan)

1. **`bucket_start` when day 1 is `not_planted`:** the design says nothing (TAW has no meaning before planting). The plan applies `Dr_0` on the **first planted day** of the plan (Task 5, `test_not_planted_day`). Confirm at STOP A.
2. **I17 row of decisions.md** ends with "Only the suggestion simulation reaches the cap": false once I23 exists. §5.8 does not list it; Task 1 amends that one clause. Confirm or remove from Task 1.
3. **Emitter not fetched for the suggestion** (it never uses `flow_lph`), so an emitter outage cannot block a suggestion. §5.5 lists emitter in the generic parallel set; Task 10 deviates on purpose. Confirm.
4. **Weather down while the season has ended:** the suggestion needs "today" from weather before the season-ended answer (§5.4 step 3), so it is a 503, not `season_ended`. Follows the design; noted only.
5. **Case 2 has 3-decimal tables** in cases.md; Task 5 compares with `abs=0.006` there, exact on the served 2-decimal values elsewhere.
