"""Compare our load tool with k6 for one cross-check session.

Reads perf/results/<prefix>-constant-seed<n>.json (load_test.py, constant rate) and
<prefix>-k6-run<n>.json (perf/k6_mix.js) and pairs them by n. Per endpoint it puts
our service time (measured from the actual send) next to k6's http_req_duration,
which is also measured from the actual send. Scheduled-time latency is not used:
k6 has no equivalent of it.

Usage, from services/registry-service:
    uv run python perf/compare_k6.py --prefix k6cross
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
EXIT_INVALID = 2
DEFAULT_TOLERANCE_MS = 5.0
STATS = ("p50", "p95", "p99")


def load_session(results_dir: Path, prefix: str) -> tuple[dict[int, dict], dict[int, dict]]:
    """(ours by seed, k6 by run number), from <prefix>-constant-seed<n>.json and
    <prefix>-k6-run<n>.json. Poisson runs, if any, are ignored."""
    ours, k6 = {}, {}
    pattern = re.compile(rf"^{re.escape(prefix)}-(constant-seed|k6-run)(\d+)\.json$")
    for path in sorted(results_dir.glob(f"{prefix}-*.json")):
        match = pattern.match(path.name)
        if not match:
            continue
        report = json.loads(path.read_text())
        (k6 if match.group(1) == "k6-run" else ours)[int(match.group(2))] = report
    return ours, k6


def load_drain(results_dir: Path, prefix: str) -> list[dict] | None:
    """Rows of <prefix>-drain.txt (written by the harness before each run), or None."""
    path = results_dir / f"{prefix}-drain.txt"
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:] if line]


def format_drain(rows: list[dict] | None) -> list[str]:
    if rows is None:
        return ["", "Drain before each run: no drain record for this session."]
    lines = ["", "Drain before each run (GET /v1/plots within 2 s twice in a row)"]
    lines += [
        f"  {row['run']:<32} {float(row['drain_s']):>7.1f} s  probes {row['probes']:>3}  "
        f"restart {row['restarted']:<3}  {row['status']}"
        for row in rows
    ]
    restarts = sum(row["restarted"] == "yes" for row in rows)
    not_drained = sum(row["status"] != "drained" for row in rows)
    lines.append(f"  restarts: {restarts}; not drained: {not_drained}")
    return lines


def our_problems(report: dict) -> list[str]:
    """Why our run cannot be compared: INVALID (generator lag or suspension) or any
    suspension at all, as in compare_runs.py."""
    problems = []
    if report["verdict"]["exit_code"] == EXIT_INVALID:
        problems.append("ours INVALID")
    if report.get("suspensions"):
        problems.append("ours suspension")
    if report.get("metadata", {}).get("arrival") != "constant":
        problems.append("ours not constant-rate")
    return problems


def k6_problems(report: dict) -> list[str]:
    """Why the k6 run cannot be compared: dropped iterations (k6 could not start a
    request on time, its generator-health check) or no measured data."""
    problems = []
    if report.get("dropped_iterations", 0) > 0:
        problems.append(f"k6 dropped_iterations {report['dropped_iterations']}")
    if not report["endpoints"]["OVERALL"].get("http_req_duration_ms"):
        problems.append("k6 no measured requests")
    return problems


def our_stats(report: dict, endpoint: str) -> dict:
    row = report["endpoints"].get(endpoint)
    if row is None:
        return {"errors": None, **{s: None for s in STATS}}
    return {"errors": row["errors"], **{s: row["service_ms"][s] for s in STATS}}


def k6_stats(report: dict, endpoint: str) -> dict:
    row = report["endpoints"].get(endpoint)
    if row is None:
        return {"errors": None, **{s: None for s in STATS}}
    duration = row.get("http_req_duration_ms") or {}
    return {"errors": row["errors"], **{s: duration.get(s) for s in STATS}}


def difference(k6_value: float | None, our_value: float | None) -> float | None:
    """k6 minus ours, in ms; positive means k6 measured more."""
    if k6_value is None or our_value is None:
        return None
    return k6_value - our_value


def compare_pair(n: int, ours: dict, k6: dict) -> dict:
    endpoints = list(ours["endpoints"])  # our order: the 11 endpoints, then OVERALL
    rows = {}
    for endpoint in endpoints:
        o, k = our_stats(ours, endpoint), k6_stats(k6, endpoint)
        rows[endpoint] = {
            "ours": o,
            "k6": k,
            "diff": {s: difference(k[s], o[s]) for s in STATS},
        }
    problems = our_problems(ours) + k6_problems(k6)
    return {
        "n": n,
        "endpoints": rows,
        "comparable": not problems,
        "problems": problems,
        "dropped_iterations": k6.get("dropped_iterations", 0),
        "lag_p99_ms": ours["checks"]["generator_lag"]["p99_ms"],
        "suspensions": len(ours.get("suspensions", [])),
        "k6_version": k6.get("metadata", {}).get("k6_version"),
    }


def compare_session(ours: dict[int, dict], k6: dict[int, dict]) -> list[dict]:
    """One entry per n that has both runs, in order."""
    return [compare_pair(n, ours[n], k6[n]) for n in sorted(set(ours) & set(k6))]


def overall_rows(pairs: list[dict]) -> dict[str, dict]:
    """Per endpoint, the mean over the comparable pairs of each side's p50/p95/p99,
    the mean difference, and the total errors on each side."""
    comparable = [p for p in pairs if p["comparable"]]
    if not comparable:
        return {}
    result = {}
    for endpoint in comparable[0]["endpoints"]:
        rows = [p["endpoints"][endpoint] for p in comparable]
        entry = {"ours": {}, "k6": {}, "diff": {}}
        for side in ("ours", "k6"):
            for s in STATS:
                values = [r[side][s] for r in rows if r[side][s] is not None]
                entry[side][s] = statistics.fmean(values) if values else None
            entry[side]["errors"] = sum(r[side]["errors"] or 0 for r in rows)
        for s in STATS:
            diffs = [r["diff"][s] for r in rows if r["diff"][s] is not None]
            entry["diff"][s] = statistics.fmean(diffs) if diffs else None
        result[endpoint] = entry
    return result


def summary(pairs: list[dict], tolerance_ms: float) -> dict:
    """Are the tools within tolerance on p95, and is the difference consistent in sign?

    `within`: every comparable pair's per-endpoint and OVERALL p95 differences are
    within the tolerance. `sign`: +1 if k6 measured more in every comparable pair's
    OVERALL p95, -1 if less in every one, None if mixed or no pairs.
    """
    comparable = [p for p in pairs if p["comparable"]]
    diffs = [
        row["diff"]["p95"]
        for p in comparable for row in p["endpoints"].values()
        if row["diff"]["p95"] is not None
    ]
    overall = [p["endpoints"]["OVERALL"]["diff"]["p95"] for p in comparable]
    signs = {(d > 0) - (d < 0) for d in overall if d is not None}
    endpoint_diffs = [
        row["diff"]["p95"]
        for p in comparable for name, row in p["endpoints"].items()
        if name != "OVERALL" and row["diff"]["p95"] is not None
    ]
    return {
        "comparable": len(comparable),
        "pairs": len(pairs),
        "tolerance_ms": tolerance_ms,
        "max_abs_p95_diff_ms": max((abs(d) for d in diffs), default=None),
        "within": bool(comparable) and all(abs(d) <= tolerance_ms for d in diffs),
        "overall_p95_diffs": overall,
        "sign": signs.pop() if len(signs) == 1 and 0 not in signs else None,
        "k6_higher_endpoints": sum(d > 0 for d in endpoint_diffs),
        "k6_lower_endpoints": sum(d < 0 for d in endpoint_diffs),
        "endpoint_comparisons": len(endpoint_diffs),
        "errors_ours": sum(p["endpoints"]["OVERALL"]["ours"]["errors"] or 0 for p in pairs),
        "errors_k6": sum(p["endpoints"]["OVERALL"]["k6"]["errors"] or 0 for p in pairs),
    }


def _fmt(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}" if signed else f"{value:.1f}"


def format_table(rows: dict[str, dict]) -> list[str]:
    head = (
        f"{'endpoint':<15}"
        + "".join(f"{f'ours {s}':>10}{f'k6 {s}':>10}" for s in STATS)
        + f"{'k6-ours p95':>13}{'err ours':>9}{'err k6':>8}"
    )
    lines = [head]
    for endpoint, row in rows.items():
        o, k, d = row["ours"], row["k6"], row["diff"]
        lines.append(
            f"{endpoint:<15}"
            + "".join(f"{_fmt(o[s]):>10}{_fmt(k[s]):>10}" for s in STATS)
            + f"{_fmt(d['p95'], signed=True):>13}"
            + f"{('-' if o['errors'] is None else o['errors']):>9}"
            + f"{('-' if k['errors'] is None else k['errors']):>8}"
        )
    return lines


def format_session(pairs: list[dict], tolerance_ms: float) -> str:
    lines = [
        "k6 cross-check: our service time (from actual send) vs k6 http_req_duration, in ms",
        "Our runs: constant rate, seeds 1-3. k6: constant-arrival-rate, unseeded.",
    ]
    versions = sorted({p["k6_version"] for p in pairs if p["k6_version"]})
    if versions:
        lines.append(f"k6: {', '.join(versions)}")
    for p in pairs:
        validity = "comparable" if p["comparable"] else "NOT COMPARABLE: " + ", ".join(p["problems"])
        lines += [
            "",
            f"Pair {p['n']}: ours constant seed {p['n']} vs k6 run {p['n']} - {validity}",
            f"  ours: generator lag p99 {_fmt(p['lag_p99_ms'])} ms, suspensions {p['suspensions']}; "
            f"k6: dropped_iterations {p['dropped_iterations']}",
        ]
        lines += format_table(p["endpoints"])

    overall = overall_rows(pairs)
    lines += ["", "Overall: mean over the comparable pairs (errors: total)"]
    lines += format_table(overall) if overall else ["  no comparable pairs"]

    s = summary(pairs, tolerance_ms)
    lines.append("")
    if not s["comparable"]:
        lines.append(f"Summary: no comparable pairs (of {s['pairs']}).")
        return "\n".join(lines)
    direction = {1: "k6 higher", -1: "k6 lower"}.get(s["sign"])
    lines.append(
        f"Summary: {s['comparable']} of {s['pairs']} pairs comparable. "
        f"Largest |k6 - ours| p95 difference {_fmt(s['max_abs_p95_diff_ms'])} ms; "
        f"all within {tolerance_ms:g} ms: {'yes' if s['within'] else 'no'}. "
        "OVERALL p95 difference per pair: "
        + ", ".join(_fmt(d, signed=True) for d in s["overall_p95_diffs"])
        + " ms; same sign in all: "
        + (f"yes ({direction})" if direction else "no")
        + f". Per endpoint: k6 higher in {s['k6_higher_endpoints']}, lower in "
        f"{s['k6_lower_endpoints']} of {s['endpoint_comparisons']}. "
        f"Errors: ours {s['errors_ours']}, k6 {s['errors_k6']}."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default="k6cross", help="session prefix, e.g. k6cross")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--tolerance-ms", type=float, default=DEFAULT_TOLERANCE_MS,
        help="largest p95 difference still counted as agreement",
    )
    args = parser.parse_args(argv)
    ours, k6 = load_session(args.results_dir, args.prefix)
    pairs = compare_session(ours, k6)
    if not pairs:
        print(
            f"No pairs of {args.prefix}-constant-seed<n>.json and {args.prefix}-k6-run<n>.json "
            f"in {args.results_dir}",
            file=sys.stderr,
        )
        return 1
    print(format_session(pairs, args.tolerance_ms))
    print("\n".join(format_drain(load_drain(args.results_dir, args.prefix))))
    return 0 if summary(pairs, args.tolerance_ms)["within"] else 1


if __name__ == "__main__":
    sys.exit(main())
