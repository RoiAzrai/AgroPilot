"""Open-model load test for the registry service (NFR-1.1).

Every request is scheduled up front and sent at its scheduled time in its own task,
so a slow server cannot slow the arrivals down (open model). Latency is measured
from the scheduled send time, which corrects coordinated omission.

Usage, from services/registry-service:
    uv run python perf/load_test.py --seed 1 --out perf/results/poisson-seed1.json
"""

import argparse
import asyncio
import contextlib
import csv
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

# (name, path template, id source). Equal weight: each arrival picks one uniformly.
ENDPOINTS: list[tuple[str, str, str | None]] = [
    ("farms_list", "/v1/farms", None),
    ("farm_by_id", "/v1/farms/{id}", "farms"),
    ("plots_list", "/v1/plots", None),
    ("plot_by_id", "/v1/plots/{id}", "plots"),
    ("plots_by_farm", "/v1/plots?farm_id={id}", "farms"),
    ("crops_list", "/v1/crops", None),
    ("crop_by_id", "/v1/crops/{id}", "crops"),
    ("soils_list", "/v1/soils", None),
    ("soil_by_id", "/v1/soils/{id}", "soils"),
    ("emitters_list", "/v1/emitters", None),
    ("emitter_by_id", "/v1/emitters/{id}", "emitters"),
]

ID_SOURCES = {
    "farms": "/v1/farms",
    "plots": "/v1/plots",
    "crops": "/v1/crops",
    "soils": "/v1/soils",
    "emitters": "/v1/emitters",
}

EXIT_PASS = 0
EXIT_NFR_FAILED = 1
EXIT_INVALID = 2
EXIT_SETUP_ERROR = 3

LITTLE_TOLERANCE = 0.05
STALL_LAG_MS = 100

HEARTBEAT_INTERVAL_S = 1.0
SUSPEND_CLOCK_GAP_S = 1.0  # wall clock ran ahead of the monotonic clock by more than this
SUSPEND_HEARTBEAT_GAP_S = 2.0  # or no heartbeat for more than this much wall time

BOOTSTRAP_RESAMPLES = 2000


class SetupError(Exception):
    """The run could not start, e.g. the service is down or a list is empty."""


@dataclass(frozen=True)
class Arrival:
    t: float  # seconds after the start of the run
    endpoint: str
    path: str


@dataclass(frozen=True)
class Result:
    endpoint: str
    scheduled: float  # all times: seconds after the start of the run
    sent: float
    done: float
    ok: bool
    status: int | None
    error: str | None
    error_detail: str | None = None


@dataclass(frozen=True)
class Heartbeat:
    mono: float  # seconds after the start of the run, monotonic clock
    wall: float  # Unix time, wall clock


# --- Schedule -------------------------------------------------------------------


def build_schedule(
    rate: float, total_s: float, arrival: str, seed: int, ids: dict[str, list[str]]
) -> list[Arrival]:
    """Generate every arrival before the run, so a run is exactly reproducible.

    Poisson: exponential gaps with mean 1/rate, as from many independent clients.
    Constant: gaps of exactly 1/rate. Timing and the endpoint/id mix come from two
    separate random streams, so both modes with the same seed send the same sequence.
    """
    timing = random.Random(f"{seed}:timing")
    mix = random.Random(f"{seed}:mix")
    schedule = []
    t = 0.0
    while True:
        if arrival == "poisson":
            t += timing.expovariate(rate)
        else:
            t = len(schedule) / rate
        if t >= total_s:
            return schedule
        name, template, source = mix.choice(ENDPOINTS)
        path = template if source is None else template.format(
            id=quote(mix.choice(ids[source]), safe="")
        )
        schedule.append(Arrival(t, name, path))


# --- Running the load -----------------------------------------------------------


async def discover_ids(client: httpx.AsyncClient) -> dict[str, list[str]]:
    """Read ids through the API's own list endpoints (black-box: no database access)."""
    ids = {}
    for source, path in ID_SOURCES.items():
        try:
            response = await client.get(path)
        except httpx.HTTPError as exc:
            raise SetupError(f"GET {path} failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise SetupError(f"GET {path} returned {response.status_code}")
        ids[source] = [item["id"] for item in response.json()]
        if not ids[source]:
            raise SetupError(f"GET {path} returned no rows; cannot request by id")
    return ids


def classify_error(exc: BaseException | None, status: int | None) -> str | None:
    """Error type of one request: timeout, connect_error, transport_error or http_<status>."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if exc is not None:
        return "transport_error"
    return None if status == 200 else f"http_{status}"


def describe_error(exc: BaseException | None, status: int | None) -> str | None:
    """Class and message of a failure, plus its cause, so an error explains itself.

    httpx often wraps a lower-level error with an empty message (for example a
    ReadError around ConnectionResetError), so the cause is kept too.
    """
    if exc is None:
        return None if status == 200 else f"HTTP {status}"
    detail = f"{type(exc).__name__}: {str(exc) or '(no message)'}"
    if exc.__cause__ is not None:
        cause = exc.__cause__
        detail += f" (caused by {type(cause).__name__}: {str(cause) or '(no message)'})"
    return detail


def build_client(args: argparse.Namespace) -> httpx.AsyncClient:
    """One keep-alive client whose limits never make it queue requests itself.

    Its idle keep-alive must be shorter than the server's (uvicorn's
    timeout_keep_alive defaults to 5 s). With equal values a pooled connection can
    be reused just as the server closes it: in a test, 35 of 480 reuses at the
    edge failed with 5.0 s and 0 of 480 with 4.0 s.
    """
    limits = httpx.Limits(
        max_connections=1000,
        max_keepalive_connections=1000,
        keepalive_expiry=args.keepalive_expiry,
    )
    return httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout, limits=limits)


async def send(client: httpx.AsyncClient, arrival: Arrival, t0: float) -> Result:
    """Send one request. Timeout, connection error or non-200 counts as an error."""
    loop = asyncio.get_running_loop()
    sent = loop.time() - t0
    status, failure = None, None
    try:
        status = (await client.get(arrival.path)).status_code
    except httpx.HTTPError as exc:
        failure = exc
    done = loop.time() - t0
    error = classify_error(failure, status)
    return Result(
        arrival.endpoint, arrival.t, sent, done, error is None, status, error,
        describe_error(failure, status),
    )


async def record_heartbeats(t0: float, beats: list[Heartbeat]) -> None:
    """Record both clocks about once per second, until cancelled.

    A suspended VM stops its monotonic clock but not the wall clock, so across a
    suspension the wall clock jumps ahead. Comparing the two is the only way to see it.
    """
    loop = asyncio.get_running_loop()
    while True:
        beats.append(Heartbeat(loop.time() - t0, time.time()))
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


async def run_load(
    client: httpx.AsyncClient, schedule: list[Arrival]
) -> tuple[list[Result], list[Heartbeat]]:
    """Launch each request at its scheduled time and never wait for a response first."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    beats: list[Heartbeat] = []
    heartbeat = asyncio.create_task(record_heartbeats(t0, beats))
    tasks = []
    for arrival in schedule:
        delay = t0 + arrival.t - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(send(client, arrival, t0)))
    results = list(await asyncio.gather(*tasks))
    heartbeat.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await heartbeat
    beats.append(Heartbeat(loop.time() - t0, time.time()))
    return results, beats


# --- Statistics -----------------------------------------------------------------


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least p% of values <= it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def distribution_ms(seconds: list[float]) -> dict[str, float | None]:
    ms = [value * 1000 for value in seconds]
    return {
        "p50": percentile(ms, 50),
        "p95": percentile(ms, 95),
        "p99": percentile(ms, 99),
        "max": max(ms) if ms else None,
        "mean": statistics.fmean(ms) if ms else None,
    }


def bootstrap_ci(
    values: list[float], rng: random.Random, p: float = 95,
    resamples: int = BOOTSTRAP_RESAMPLES, level: float = 95,
) -> list[float] | None:
    """Percentile bootstrap confidence interval for the p-th percentile.

    Resample the values with replacement, take the nearest-rank p-th percentile of
    each resample, and keep the middle `level`% of those estimates. It covers
    sampling noise only: requests are treated as independent, so a change in the
    machine's state during the run is not part of the interval.
    """
    if not values:
        return None
    estimates = sorted(percentile(rng.choices(values, k=len(values)), p) for _ in range(resamples))
    tail = (100 - level) / 2
    return [percentile(estimates, tail), percentile(estimates, 100 - tail)]


def add_p95_ci(rows: dict[str, dict], measured: list[Result], seed: int) -> None:
    """Attach a p95 [low, high] interval to every latency row, from its own random stream."""
    rng = random.Random(f"{seed}:bootstrap")
    for name in rows:
        group = measured if name == "OVERALL" else [r for r in measured if r.endpoint == name]
        latencies = [(r.done - r.scheduled) * 1000 for r in group if r.ok]
        rows[name]["latency_ms"]["p95_ci"] = bootstrap_ci(latencies, rng)


def endpoint_row(results: list[Result]) -> dict:
    """Latency is measured from the scheduled time; service time from the actual send."""
    ok = [r for r in results if r.ok]
    return {
        "requests": len(results),
        "errors": len(results) - len(ok),
        "latency_ms": distribution_ms([r.done - r.scheduled for r in ok]),
        "service_ms": distribution_ms([r.done - r.sent for r in ok]),
    }


def summarize(measured: list[Result]) -> dict[str, dict]:
    rows = {
        name: endpoint_row([r for r in measured if r.endpoint == name])
        for name, _, _ in ENDPOINTS
    }
    rows["OVERALL"] = endpoint_row(measured)
    return rows


def arrival_stats(measured: list[Result], window_s: float) -> dict:
    """Achieved rate and the coefficient of variation of the actual gaps between sends.

    CV = stdev / mean of the gaps: about 1.0 for Poisson arrivals, about 0 for constant.
    """
    sends = sorted(r.sent for r in measured)
    gaps = [b - a for a, b in zip(sends, sends[1:])]
    mean_gap = statistics.fmean(gaps) if gaps else None
    return {
        "achieved_rate": len(measured) / window_s,
        "mean_gap_ms": mean_gap * 1000 if mean_gap else None,
        "cv": statistics.pstdev(gaps) / mean_gap if mean_gap else None,
    }


def lag_stats(measured: list[Result], bound_ms: float) -> dict:
    """Generator lag = actual send - scheduled. A large lag means the client was late."""
    lags = [(r.sent - r.scheduled) * 1000 for r in measured]
    p99 = percentile(lags, 99)
    return {
        "p50_ms": percentile(lags, 50),
        "p99_ms": p99,
        "max_ms": max(lags) if lags else None,
        "bound_ms": bound_ms,
        "valid": p99 is not None and p99 <= bound_ms,
    }


def time_average_in_flight(
    intervals: list[tuple[float, float]], start: float, end: float
) -> float:
    """Integrate the number of in-flight requests over [start, end], divided by its length."""
    events = []
    for begin, finish in intervals:
        begin, finish = max(begin, start), min(finish, end)
        if finish > begin:
            events += [(begin, 1), (finish, -1)]
    events.sort()
    area, count, previous = 0.0, 0, start
    for t, delta in events:
        area += count * (t - previous)
        count += delta
        previous = t
    return area / (end - start)


def littles_law(measured: list[Result], start: float, end: float) -> dict:
    """Little's Law, L = lambda x W: average in-flight count = arrival rate x mean time in system.

    Both sides use the same requests and the same definition: in system from the
    scheduled time to completion, clipped to the measurement window.
    """
    if not measured:
        return {"measured_l": None, "lambda_w": None, "relative_difference": None}
    measured_l = time_average_in_flight([(r.scheduled, r.done) for r in measured], start, end)
    rate = len(measured) / (end - start)
    mean_w = statistics.fmean(r.done - r.scheduled for r in measured)
    lambda_w = rate * mean_w
    return {
        "measured_l": measured_l,
        "lambda_w": lambda_w,
        "relative_difference": abs(measured_l - lambda_w) / lambda_w if lambda_w else None,
    }


def utilization(rate: float, mean_service_ms: float | None) -> float | None:
    """rho = lambda x mean service time: the share of time a single server would be busy."""
    return rate * mean_service_ms / 1000 if mean_service_ms is not None else None


def errors_by_type(results: list[Result]) -> dict[str, int]:
    return dict(Counter(r.error for r in results if r.error).most_common())


def errors_by_detail(results: list[Result]) -> dict[str, int]:
    return dict(Counter(r.error_detail for r in results if r.error).most_common())


def find_stalls(results: list[Result], threshold_ms: float = STALL_LAG_MS) -> list[dict]:
    """Periods where the generator ran late: consecutive requests (in schedule order)
    whose lag exceeded the threshold. A stall starts at the first late request's
    scheduled time and ends when the last one was finally sent.
    """
    ordered = sorted(results, key=lambda r: r.scheduled)
    groups, current = [], []
    for r in ordered:
        if (r.sent - r.scheduled) * 1000 > threshold_ms:
            current.append(r)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    stalls = []
    for group in groups:
        start, end = group[0].scheduled, max(r.sent for r in group)
        sent_inside = [r for r in results if start <= r.sent <= end]
        stalls.append({
            "start_s": start,
            "duration_s": end - start,
            "requests": len(group),
            "max_lag_ms": max((r.sent - r.scheduled) * 1000 for r in group),
            "max_service_ms": max((r.done - r.sent) * 1000 for r in sent_inside),
        })
    return stalls


def detect_suspensions(beats: list[Heartbeat], run_end_s: float) -> list[dict]:
    """Find periods where the VM was suspended: between two heartbeats, the wall clock
    advanced more than the monotonic clock by over 1 s, or no heartbeat came for over
    2 s of wall time. `in_run` is true when it started during warm-up or measurement.
    """
    found = []
    for before, after in zip(beats, beats[1:]):
        wall_gap = after.wall - before.wall
        unaccounted = wall_gap - (after.mono - before.mono)
        if unaccounted > SUSPEND_CLOCK_GAP_S:
            kind, duration = "clock_gap", unaccounted
        elif wall_gap > SUSPEND_HEARTBEAT_GAP_S:
            kind, duration = "no_heartbeat", wall_gap
        else:
            continue
        found.append({
            "start_s": before.mono,
            "wall_start": datetime.fromtimestamp(before.wall, timezone.utc).isoformat(
                timespec="seconds"
            ),
            "duration_s": duration,
            "kind": kind,
            "in_run": 0 <= before.mono < run_end_s,
        })
    return found


def write_timeline(path: Path, results: list[Result], start: float, end: float) -> None:
    """One raw row per request, times in seconds from the start of the run."""
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "scheduled", "sent", "done", "endpoint", "status", "error", "in_window", "error_detail",
        ])
        for r in sorted(results, key=lambda r: r.scheduled):
            writer.writerow([
                f"{r.scheduled:.6f}", f"{r.sent:.6f}", f"{r.done:.6f}", r.endpoint,
                r.status if r.status is not None else "", r.error or "",
                int(start <= r.scheduled < end), r.error_detail or "",
            ])


# --- Verdict, metadata and report -----------------------------------------------


def verdict(
    rows: dict[str, dict], lag: dict, threshold_ms: float, suspensions: list[dict] = ()
) -> tuple[int, list[str]]:
    """Pass only if every endpoint meets the p95 threshold with no errors on a valid run."""
    reasons = []
    for name, row in rows.items():
        p95 = row["latency_ms"]["p95"]
        if row["errors"]:
            reasons.append(f"{name}: {row['errors']} errors")
        if p95 is None:
            reasons.append(f"{name}: no successful requests")
        elif p95 > threshold_ms:
            reasons.append(f"{name}: p95 {p95:.1f} ms > {threshold_ms:g} ms")
    invalid = [
        f"INVALID: VM suspended for {s['duration_s']:.1f} s at {s['start_s']:.1f} s into the "
        f"run (wall {s['wall_start']}); the monotonic clock stopped, so timings around it "
        "cannot be trusted"
        for s in suspensions if s["in_run"]
    ]
    if not lag["valid"]:
        invalid.insert(
            0,
            f"INVALID: generator lag p99 {lag['p99_ms']} ms > {lag['bound_ms']:g} ms "
            "(the load generator, not the server, was the bottleneck)",
        )
    if invalid:
        return EXIT_INVALID, invalid + reasons
    return (EXIT_NFR_FAILED, reasons) if reasons else (EXIT_PASS, [])


def ci_upper_above(rows: dict[str, dict], threshold_ms: float) -> list[str]:
    """Endpoints whose upper p95 CI bound is above the threshold (empty: all within)."""
    return [
        name for name, row in rows.items()
        if row["latency_ms"].get("p95_ci") is None or row["latency_ms"]["p95_ci"][1] > threshold_ms
    ]


def git_commit() -> str:
    repo = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("+dirty" if dirty else "")


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def run_metadata(args: argparse.Namespace, started_at: datetime) -> dict:
    return {
        "started_at": started_at.isoformat(timespec="seconds"),
        "commit": git_commit(),
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu": cpu_model(),
        "arrival": args.arrival,
        "seed": args.seed,
        "rate": args.rate,
        "warmup_s": args.warmup,
        "duration_s": args.duration,
        "timeout_s": args.timeout,
        "threshold_ms": args.threshold_ms,
        "max_lag_ms": args.max_lag_ms,
        "keepalive_expiry_s": args.keepalive_expiry,
        "base_url": args.base_url,
    }


async def measure(args: argparse.Namespace) -> tuple[dict, list[Result]]:
    """Discover ids, run warm-up plus measurement, and build the report."""
    started_at = datetime.now(timezone.utc)
    async with build_client(args) as client:
        ids = await discover_ids(client)
        schedule = build_schedule(
            args.rate, args.warmup + args.duration, args.arrival, args.seed, ids
        )
        results, beats = await run_load(client, schedule)

    start, end = args.warmup, args.warmup + args.duration
    measured = [r for r in results if start <= r.scheduled < end]
    rows = summarize(measured)
    add_p95_ci(rows, measured, args.seed)
    arrivals = arrival_stats(measured, args.duration)
    lag = lag_stats(measured, args.max_lag_ms)
    little = littles_law(measured, start, end)
    rho = utilization(arrivals["achieved_rate"], rows["OVERALL"]["service_ms"]["mean"])
    suspensions = detect_suspensions(beats, end)
    exit_code, reasons = verdict(rows, lag, args.threshold_ms, suspensions)
    report = {
        "metadata": run_metadata(args, started_at),
        "endpoints": rows,
        "ci_upper_above_threshold": ci_upper_above(rows, args.threshold_ms),
        "errors_by_type": errors_by_type(measured),
        "errors_by_detail": errors_by_detail(measured),
        # Over the whole run, warm-up included: a stall there still says something about the machine.
        "stalls": find_stalls(results),
        "suspensions": suspensions,
        "heartbeats": len(beats),
        "checks": {
            "arrivals": arrivals,
            "generator_lag": lag,
            "littles_law": little,
            "utilization": {"rho": rho},
        },
        "verdict": {"exit_code": exit_code, "passed": exit_code == EXIT_PASS, "reasons": reasons},
    }
    return report, results


def run(args: argparse.Namespace) -> dict:
    return asyncio.run(measure(args))[0]


def _fmt(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def format_p95_ci(stats: dict) -> str:
    ci = stats.get("p95_ci")
    return _fmt(stats["p95"]) + (f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else "")


def format_table(rows: dict[str, dict], key: str) -> list[str]:
    with_ci = key == "latency_ms"
    p95_head = "p95 [95% CI]" if with_ci else "p95"
    p95_width = 22 if with_ci else 8
    lines = [
        f"{'endpoint':<15}{'requests':>9}{'errors':>7}{'p50':>8}{p95_head:>{p95_width}}"
        f"{'p99':>8}{'max':>8}{'mean':>8}"
    ]
    for name, row in rows.items():
        stats = row[key]
        p95 = format_p95_ci(stats) if with_ci else _fmt(stats["p95"])
        lines.append(
            f"{name:<15}{row['requests']:>9}{row['errors']:>7}{_fmt(stats['p50']):>8}"
            f"{p95:>{p95_width}}"
            + "".join(f"{_fmt(stats[k]):>8}" for k in ("p99", "max", "mean"))
        )
    return lines


def interpret(report: dict) -> list[str]:
    """One line per queueing check, saying what the number means for this run."""
    meta, checks = report["metadata"], report["checks"]
    arrivals, lag = checks["arrivals"], checks["generator_lag"]
    little, rho = checks["littles_law"], checks["utilization"]["rho"]

    expected_cv = 1.0 if meta["arrival"] == "poisson" else 0.0
    cv = arrivals["cv"]
    cv_ok = cv is not None and abs(cv - expected_cv) <= (0.15 if expected_cv else 0.1)
    lines = [
        f"1. Arrivals: rate {_fmt(arrivals['achieved_rate'], 2)}/s (target {meta['rate']:g}), "
        f"mean gap {_fmt(arrivals['mean_gap_ms'])} ms, CV {_fmt(cv, 3)} "
        f"(expected ~{expected_cv:g}). "
        + ("Arrivals follow the intended process." if cv_ok
           else "Arrivals deviate from the intended process."),
        f"2. Generator lag: p50 {_fmt(lag['p50_ms'], 2)} ms, p99 {_fmt(lag['p99_ms'], 2)} ms, "
        f"max {_fmt(lag['max_ms'], 2)} ms (validity bound p99 <= {lag['bound_ms']:g} ms = "
        f"{lag['bound_ms'] / meta['threshold_ms'] * 100:g}% of the {meta['threshold_ms']:g} ms "
        "budget). Lag is included in the measured latency, so it can only make results "
        "worse: a PASS is never caused by lag. "
        + ("Requests left on time: the server was measured, not the client." if lag["valid"]
           else "INVALID: the client was slow, so FAIL verdicts and tail values cannot be "
                "blamed on the server."),
    ]
    difference = little["relative_difference"]
    lines.append(
        "3. Little's Law consistency check (L = lambda x W over the same requests; "
        f"near-identity by construction): measured L {_fmt(little['measured_l'], 4)} vs "
        f"lambda x W {_fmt(little['lambda_w'], 4)}, difference "
        f"{_fmt(difference * 100 if difference is not None else None, 2)}%. "
        + ("Bookkeeping is consistent; this is not an independent validation."
           if difference is not None and difference <= LITTLE_TOLERANCE
           else "Bookkeeping mismatch: suspect lost requests or a wrong window.")
    )
    lines.append(
        f"4. Utilization: rho {_fmt(rho, 4)}. "
        + ("The server is mostly idle, so queueing adds little to the latency."
           if rho is not None and rho < 0.5
           else "The server is busy; queueing delay grows quickly from here.")
    )
    return lines


def format_report(report: dict) -> str:
    meta = report["metadata"]
    lines = ["NFR-1.1 load test", ""]
    width = max(len(key) for key in meta) + 2
    lines += [f"  {key:<{width}}{value}" for key, value in meta.items()]
    lines += ["", "Latency from scheduled send time (ms) - used for the verdict"]
    lines += format_table(report["endpoints"], "latency_ms")
    above = report["ci_upper_above_threshold"]
    lines.append(
        f"Info: upper p95 CI bound <= {meta['threshold_ms']:g} ms for every endpoint: "
        + ("yes" if not above else f"no ({', '.join(above)})")
        + ". The verdict uses the point p95."
    )
    lines += ["", "Service time from actual send time (ms)"]
    lines += format_table(report["endpoints"], "service_ms")
    errors = report["errors_by_type"]
    lines += ["", "Errors by type (measurement window)"]
    lines += [f"  {kind:<16}{count}" for kind, count in errors.items()] or ["  none"]
    lines += ["", "Errors by detail (measurement window)"]
    lines += [
        f"  {count:>5} x {detail}" for detail, count in report["errors_by_detail"].items()
    ] or ["  none"]
    lines += ["", f"Stalls: generator lag > {STALL_LAG_MS} ms (whole run, seconds from start)"]
    lines += [
        f"  at {s['start_s']:8.2f} s  lasted {s['duration_s'] * 1000:8.1f} ms  "
        f"requests {s['requests']:4}  max lag {s['max_lag_ms']:8.1f} ms  "
        f"max service {s['max_service_ms']:8.1f} ms"
        for s in report["stalls"]
    ] or ["  none"]
    lines += [
        "",
        f"Suspensions: wall clock ran ahead of the monotonic clock "
        f"({report['heartbeats']} heartbeats)",
    ]
    lines += [
        f"  at {s['start_s']:8.2f} s (wall {s['wall_start']})  lasted {s['duration_s']:8.1f} s  "
        f"{s['kind']}  " + ("INSIDE the run" if s["in_run"] else "outside the run")
        for s in report["suspensions"]
    ] or ["  none"]
    lines += ["", "Queueing checks"] + interpret(report)
    result = report["verdict"]
    lines += ["", "VERDICT: " + ("PASS" if result["passed"] else f"FAIL (exit {result['exit_code']})")]
    lines += [f"  - {reason}" for reason in result["reasons"]]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--rate", type=float, default=10.0, help="mean requests per second")
    parser.add_argument("--arrival", choices=["poisson", "constant"], default="poisson")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--warmup", type=float, default=20.0, help="seconds, excluded")
    parser.add_argument("--duration", type=float, default=300.0, help="measured seconds")
    parser.add_argument("--timeout", type=float, default=5.0, help="per request, seconds")
    parser.add_argument("--threshold-ms", type=float, default=100.0, help="p95 limit")
    parser.add_argument(
        "--max-lag-ms", type=float, default=10.0,
        help="generator lag p99 limit (10 ms = 10%% of the 100 ms budget)",
    )
    parser.add_argument(
        "--keepalive-expiry", type=float, default=4.0,
        help="client idle keep-alive, seconds; must be shorter than the server's (uvicorn: 5 s)",
    )
    parser.add_argument(
        "--out", type=Path,
        help="write the JSON summary to this file, and the per-request timeline next to it (.csv)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report, results = asyncio.run(measure(args))
    except SetupError as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return EXIT_SETUP_ERROR
    print(format_report(report))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        timeline = args.out.with_suffix(".csv")
        write_timeline(timeline, results, args.warmup, args.warmup + args.duration)
        print(f"\nJSON summary written to {args.out}\nTimeline written to {timeline}")
    return report["verdict"]["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
