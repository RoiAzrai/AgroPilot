"""Compare the runs of one measurement session (NFR-1.1).

Reads <prefix>-*.json from perf/results/ and prints the official result (the
Poisson runs) and the paired Poisson vs constant comparison, one row per seed.

Usage, from services/registry-service:
    uv run python perf/compare_runs.py --prefix paired
"""

import argparse
import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
EXIT_INVALID = 2


def load_session(results_dir: Path, prefix: str) -> dict[tuple[str, int], dict]:
    """Reports keyed by (arrival, seed), read from <prefix>-*.json."""
    runs = {}
    for path in sorted(results_dir.glob(f"{prefix}-*.json")):
        report = json.loads(path.read_text())
        meta = report.get("metadata", {})
        if "arrival" in meta and "seed" in meta:
            runs[(meta["arrival"], meta["seed"])] = report
    return runs


def p95_of(report: dict, endpoint: str = "OVERALL") -> float | None:
    return report["endpoints"][endpoint]["latency_ms"]["p95"]


def ci_of(report: dict, endpoint: str = "OVERALL") -> list[float] | None:
    return report["endpoints"][endpoint]["latency_ms"].get("p95_ci")


def with_ci(report: dict, endpoint: str = "OVERALL") -> str:
    p95, ci = p95_of(report, endpoint), ci_of(report, endpoint)
    text = "-" if p95 is None else f"{p95:.1f}"
    return text + (f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else " [no CI]")


def why_not_comparable(report: dict) -> str | None:
    if report["verdict"]["exit_code"] == EXIT_INVALID:
        return "INVALID"
    if report.get("suspensions"):
        return "suspension"
    return None


def official_result(runs: dict[tuple[str, int], dict]) -> dict:
    """NFR-1.1 from the Poisson runs: PASS only if there is at least one and all passed."""
    poisson = {seed: report for (arrival, seed), report in sorted(runs.items()) if arrival == "poisson"}
    worst = None
    for seed, report in poisson.items():
        for endpoint in report["endpoints"]:
            if endpoint == "OVERALL" or p95_of(report, endpoint) is None:
                continue
            if worst is None or p95_of(report, endpoint) > worst["p95"]:
                worst = {"p95": p95_of(report, endpoint), "endpoint": endpoint, "seed": seed}
    failed = [seed for seed, report in poisson.items() if not report["verdict"]["passed"]]
    return {
        "seeds": list(poisson),
        "worst": worst,
        "failed_seeds": failed,
        "passed": bool(poisson) and not failed,
    }


def paired_rows(runs: dict[tuple[str, int], dict]) -> list[dict]:
    """One row per seed that has both a Poisson and a constant run."""
    rows = []
    seeds = sorted({seed for arrival, seed in runs if arrival == "poisson"}
                   & {seed for arrival, seed in runs if arrival == "constant"})
    for seed in seeds:
        poisson, constant = runs[("poisson", seed)], runs[("constant", seed)]
        reasons = [
            f"{name} {why}" for name, report in (("poisson", poisson), ("constant", constant))
            if (why := why_not_comparable(report))
        ]
        p_ci, c_ci = ci_of(poisson), ci_of(constant)
        rows.append({
            "seed": seed,
            "poisson": poisson,
            "constant": constant,
            "difference_ms": p95_of(poisson) - p95_of(constant),
            "comparable": not reasons,
            "reasons": reasons,
            "ci_overlap": (
                p_ci is not None and c_ci is not None
                and p_ci[0] <= c_ci[1] and c_ci[0] <= p_ci[1]
            ),
        })
    return rows


def pair_summary(rows: list[dict]) -> dict:
    comparable = [row for row in rows if row["comparable"]]
    signs = {(row["difference_ms"] > 0) - (row["difference_ms"] < 0) for row in comparable}
    return {
        "comparable": len(comparable),
        "same_sign": len(comparable) > 0 and len(signs) == 1 and 0 not in signs,
        "sign": signs.pop() if len(signs) == 1 else None,
        "ci_overlaps": sum(row["ci_overlap"] for row in comparable),
    }


def format_session(runs: dict[tuple[str, int], dict]) -> str:
    lines = []
    official = official_result(runs)
    poisson = {seed: runs[("poisson", seed)] for seed in official["seeds"]}
    lines += ["Official NFR-1.1 result (Poisson runs): p95 [95% CI] in ms", ""]
    if poisson:
        endpoints = list(next(iter(poisson.values()))["endpoints"])
        lines.append(f"{'endpoint':<15}" + "".join(f"{f'seed {s}':>24}" for s in poisson))
        for endpoint in endpoints:
            lines.append(
                f"{endpoint:<15}" + "".join(f"{with_ci(r, endpoint):>24}" for r in poisson.values())
            )
        lines.append(f"{'verdict':<15}" + "".join(
            f"{('PASS' if r['verdict']['passed'] else 'FAIL (exit ' + str(r['verdict']['exit_code']) + ')'):>24}"
            for r in poisson.values()
        ))
    worst = official["worst"]
    lines.append("")
    if worst:
        lines.append(
            f"Worst p95: {worst['p95']:.1f} ms ({worst['endpoint']}, Poisson seed {worst['seed']})"
        )
    lines.append(
        f"Overall: {'PASS' if official['passed'] else 'FAIL'} "
        f"({len(official['seeds'])} Poisson runs"
        + (f"; failed seeds: {official['failed_seeds']}" if official["failed_seeds"] else "")
        + ")"
    )

    rows = paired_rows(runs)
    lines += ["", "Paired comparison (same seed = same requests; adjacent runs): overall p95 [95% CI]"]
    lines.append(f"{'seed':<6}{'Poisson':>24}{'constant':>24}{'P - C (ms)':>12}  note")
    for row in rows:
        note = ("comparable, CIs " + ("overlap" if row["ci_overlap"] else "do not overlap")
                if row["comparable"] else "not comparable: " + ", ".join(row["reasons"]))
        lines.append(
            f"{row['seed']:<6}{with_ci(row['poisson']):>24}{with_ci(row['constant']):>24}"
            f"{row['difference_ms']:>+12.1f}  {note}"
        )
    summary = pair_summary(rows)
    if summary["comparable"]:
        direction = {1: "Poisson higher", -1: "constant higher"}.get(summary["sign"], "")
        lines.append(
            f"Summary: {summary['comparable']} comparable pairs; difference has the same sign in all: "
            + (f"yes ({direction})" if summary["same_sign"] else "no")
            + f"; CIs overlap in {summary['ci_overlaps']} of {summary['comparable']}."
        )
    else:
        lines.append("Summary: no comparable pairs.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default="paired", help="session prefix, e.g. paired")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    runs = load_session(args.results_dir, args.prefix)
    if not runs:
        print(f"No {args.prefix}-*.json reports in {args.results_dir}", file=sys.stderr)
        return 1
    print(format_session(runs))
    return 0 if official_result(runs)["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
