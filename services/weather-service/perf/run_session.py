"""NFR-2.3 measurement session (design 5.11): fresh forecast p95 <= 100 ms at 10 req/s,
with zero calls to Open-Meteo.

Starts the local fake provider and the service pointed at it, warms the cache (one
request per point), runs perf/load_test.py for Poisson seeds 1-3, prints the summary,
then checks that the fake provider got no call after the warm-up. Both child
processes are always stopped.

Usage, from services/weather-service:
    uv run python perf/run_session.py --prefix official
Exit codes: 0 pass, 1 fail, 2 invalid, 3 setup error.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

SERVICE_DIR = Path(__file__).resolve().parent.parent
RESULTS = SERVICE_DIR / "perf" / "results"
SEEDS = (1, 2, 3)
STARTUP_TIMEOUT_S = 30
STOP_TIMEOUT_S = 10

# Same points as the load tool (a copy: the load tool runs as its own process).
POINTS = [(31.25, 34.79), (31.26, 34.80), (31.40, 34.60), (31.41, 34.61)]

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INVALID = 2
EXIT_SETUP_ERROR = 3

RUN_STATUS = {EXIT_PASS: "PASS", EXIT_FAIL: "FAIL", EXIT_INVALID: "INVALID"}


class SetupError(Exception):
    """The session could not be set up or a run could not start."""


# --- Pure parts: summary and zero-calls check -----------------------------------


def session_summary(reports: list[dict]) -> dict:
    """Worst p95 across endpoints and runs; PASS only if every run passed.

    Any INVALID run makes the session INVALID (its timings cannot be trusted);
    otherwise any FAIL makes it FAIL. The OVERALL row is not an endpoint.
    """
    runs = [RUN_STATUS[r["verdict"]["exit_code"]] for r in reports]
    worst = None
    for index, report in enumerate(reports, start=1):
        for name, row in report["endpoints"].items():
            p95 = row["latency_ms"]["p95"]
            if name != "OVERALL" and p95 is not None and (worst is None or p95 > worst[0]):
                worst = (p95, index, name)
    if "INVALID" in runs:
        status = "INVALID"
    elif "FAIL" in runs:
        status = "FAIL"
    else:
        status = "PASS"
    return {
        "status": status,
        "runs": runs,
        "worst_p95_ms": worst[0] if worst else None,
        "worst_run": worst[1] if worst else None,
        "worst_endpoint": worst[2] if worst else None,
    }


def zero_calls_check(calls_after_warmup: int, calls_after_runs: int) -> dict:
    """The fake provider's count must not change between the warm-up and the last run."""
    during = calls_after_runs - calls_after_warmup
    return {"passed": during == 0, "calls_during_runs": during}


def session_exit_code(summary: dict, zero_calls: dict) -> int:
    """Provider calls during the runs fail the session whatever the timings say."""
    if not zero_calls["passed"]:
        return EXIT_FAIL
    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "INVALID": EXIT_INVALID}[summary["status"]]


def format_summary(
    prefix: str, summary: dict, zero_calls: dict, calls: tuple[int, int], exit_code: int
) -> list[str]:
    worst = summary["worst_p95_ms"]
    lines = [f"Session summary ({prefix})"]
    lines += [
        f"  run {i}/3 Poisson seed {seed}: {status}"
        for i, (seed, status) in enumerate(zip(SEEDS, summary["runs"]), start=1)
    ]
    lines.append(
        "  worst p95 across endpoints and runs: "
        + ("-" if worst is None else
           f"{worst:.1f} ms (run {summary['worst_run']}, {summary['worst_endpoint']})")
    )
    lines.append(f"  NFR-2.3 p95 <= 100 ms at 10 req/s: {summary['status']}")
    lines.append(
        f"Zero-calls check: provider calls after warm-up {calls[0]}, after the last run "
        f"{calls[1]} ({zero_calls['calls_during_runs']} during the runs): "
        + ("PASS" if zero_calls["passed"] else "FAIL")
    )
    lines.append(f"SESSION: {['PASS', 'FAIL', 'INVALID', 'SETUP ERROR'][exit_code]} (exit {exit_code})")
    return lines


# --- Processes ------------------------------------------------------------------


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start(command: list[str], log: Path, env: dict[str, str] | None = None) -> subprocess.Popen:
    """Own process group, so stop() reaches uv and the uvicorn it starts together."""
    with log.open("ab") as out:
        return subprocess.Popen(
            command, cwd=SERVICE_DIR, env=env, stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(STOP_TIMEOUT_S)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def wait_until_up(url: str, process: subprocess.Popen, name: str, log: Path) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SetupError(f"{name} exited with code {process.returncode}; see {log}")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise SetupError(f"{name} did not answer {url} within {STARTUP_TIMEOUT_S} s; see {log}")


def provider_calls(provider_url: str) -> int:
    return httpx.get(f"{provider_url}/calls", timeout=5).json()["calls"]


def warm_cache(service_url: str) -> None:
    """One request per point; every answer must be 200 and fresh."""
    for lat, lon in POINTS:
        response = httpx.get(
            f"{service_url}/v1/forecast", params={"lat": lat, "lon": lon, "days": 7}, timeout=10
        )
        if response.status_code != 200 or response.json().get("stale") is not False:
            raise SetupError(
                f"cache warm-up: lat={lat} lon={lon} returned {response.status_code} "
                f"{response.text[:200]}"
            )


def run_load_test(args: argparse.Namespace, service_url: str, seed: int) -> dict:
    out = RESULTS / f"{args.prefix}-poisson-seed{seed}.json"
    code = subprocess.run(
        [
            sys.executable, "perf/load_test.py", "--base-url", service_url,
            "--arrival", "poisson", "--seed", str(seed),
            "--warmup", str(args.warmup), "--duration", str(args.duration), "--out", str(out),
        ],
        cwd=SERVICE_DIR,
    ).returncode
    if code not in RUN_STATUS:
        raise SetupError(f"load test for seed {seed} exited with code {code}")
    return json.loads(out.read_text())


def session(args: argparse.Namespace) -> int:
    service_url = f"http://127.0.0.1:{args.service_port}"
    provider_url = f"http://127.0.0.1:{args.provider_port}"
    for port in (args.service_port, args.provider_port):
        if port_in_use(port):
            raise SetupError(f"port {port} is already in use; choose another with the options")

    provider_log = RESULTS / f"{args.prefix}-provider.log"
    service_log = RESULTS / f"{args.prefix}-service.log"
    # The environment wins over the service's .env (which is never read here).
    env = {**os.environ, "PROVIDER_BASE_URL": f"{provider_url}/v1/forecast"}
    children = []
    try:
        print("[setup] starting the fake provider and the service", flush=True)
        children.append(start(
            [sys.executable, "perf/fake_provider.py", "--port", str(args.provider_port)],
            provider_log,
        ))
        wait_until_up(f"{provider_url}/calls", children[0], "fake provider", provider_log)
        children.append(start(
            [
                "uv", "run", "uvicorn", "main:app", "--host", "127.0.0.1",
                "--port", str(args.service_port), "--workers", "1", "--log-level", "warning",
            ],
            service_log, env,
        ))
        wait_until_up(f"{service_url}/health", children[1], "service", service_log)

        print("[cache warm-up] one request per point", flush=True)
        warm_cache(service_url)
        calls_after_warmup = provider_calls(provider_url)

        reports = []
        for i, seed in enumerate(SEEDS, start=1):
            print(f"[run {i}/3] Poisson seed {seed}", flush=True)
            reports.append(run_load_test(args, service_url, seed))
        calls_after_runs = provider_calls(provider_url)
    finally:
        for child in reversed(children):
            stop(child)

    summary = session_summary(reports)
    zero_calls = zero_calls_check(calls_after_warmup, calls_after_runs)
    exit_code = session_exit_code(summary, zero_calls)
    lines = format_summary(
        args.prefix, summary, zero_calls, (calls_after_warmup, calls_after_runs), exit_code
    )
    text = "\n".join(lines)
    print("\n" + text)
    (RESULTS / f"{args.prefix}-summary.txt").write_text(text + "\n")
    return exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", required=True, help="result file prefix in perf/results/")
    parser.add_argument("--warmup", type=float, default=20.0, help="load warm-up seconds per run")
    parser.add_argument("--duration", type=float, default=300.0, help="measured seconds per run")
    parser.add_argument("--service-port", type=int, default=8001)
    parser.add_argument("--provider-port", type=int, default=8091)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.prefix or "/" in args.prefix or args.prefix.startswith("."):
        print(f"Setup error: invalid prefix {args.prefix!r}", file=sys.stderr)
        return EXIT_SETUP_ERROR
    existing = sorted(RESULTS.glob(f"{args.prefix}-*"))
    if existing:
        print(
            f"Setup error: {existing[0]} exists; results are never overwritten, "
            "choose another --prefix",
            file=sys.stderr,
        )
        return EXIT_SETUP_ERROR
    RESULTS.mkdir(parents=True, exist_ok=True)
    # SIGTERM takes the same path as Ctrl+C, so the children are stopped either way.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        return session(args)
    except SetupError as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
    except httpx.HTTPError as exc:
        print(f"Setup error: {type(exc).__name__}: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInterrupted; both processes stopped.", file=sys.stderr)
    return EXIT_SETUP_ERROR


if __name__ == "__main__":
    sys.exit(main())
