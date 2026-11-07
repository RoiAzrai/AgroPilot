import json

import pytest

from perf.compare_k6 import (
    compare_session,
    load_session,
    main,
    overall_rows,
    summary,
)


def ours(seed, p95, errors=0, exit_code=0, suspensions=(), lag=1.0, arrival="constant"):
    """A minimal load_test.py report: service_ms is what compare_k6.py reads."""
    def row(p):
        return {
            "errors": errors,
            "latency_ms": {"p50": 99.0, "p95": 99.0, "p99": 99.0},  # must be ignored
            "service_ms": {"p50": p - 5, "p95": p, "p99": p + 5},
        }
    return {
        "metadata": {"arrival": arrival, "seed": seed},
        "endpoints": {"farms_list": row(p95), "OVERALL": row(p95)},
        "checks": {"generator_lag": {"p99_ms": lag}},
        "suspensions": list(suspensions),
        "verdict": {"exit_code": exit_code, "passed": exit_code == 0, "reasons": []},
    }


def k6(p95, errors=0, dropped=0, version="k6 v2.3.0 (test)"):
    """A minimal k6_mix.js summary report."""
    def row(p):
        return {
            "requests": 100,
            "errors": errors,
            "http_req_duration_ms": {"p50": p - 5, "p95": p, "p99": p + 5, "max": p + 9},
        }
    return {
        "tool": "k6",
        "metadata": {"k6_version": version},
        "endpoints": {"farms_list": row(p95), "OVERALL": row(p95)},
        "dropped_iterations": dropped,
        "valid": dropped == 0,
    }


def write(directory, name, report):
    (directory / name).write_text(json.dumps(report))


@pytest.fixture
def results(tmp_path):
    write(tmp_path, "x-constant-seed1.json", ours(1, 20.0))
    write(tmp_path, "x-k6-run1.json", k6(18.0))
    write(tmp_path, "x-constant-seed2.json", ours(2, 21.0))
    write(tmp_path, "x-k6-run2.json", k6(19.5))
    write(tmp_path, "x-constant-seed3.json", ours(3, 19.0))
    write(tmp_path, "x-k6-run3.json", k6(18.0))
    # Not part of the session: another prefix, a Poisson run, a comparison file.
    write(tmp_path, "y-k6-run1.json", k6(90.0))
    write(tmp_path, "x-poisson-seed1.json", ours(1, 80.0, arrival="poisson"))
    write(tmp_path, "x-comparison.json", {})
    return tmp_path


def test_load_session_pairs_by_number(results):
    our_runs, k6_runs = load_session(results, "x")
    assert sorted(our_runs) == [1, 2, 3]
    assert sorted(k6_runs) == [1, 2, 3]
    assert k6_runs[1]["endpoints"]["OVERALL"]["http_req_duration_ms"]["p95"] == 18.0


def test_pair_uses_service_time_not_latency(results):
    pairs = compare_session(*load_session(results, "x"))
    row = pairs[0]["endpoints"]["farms_list"]
    assert row["ours"]["p95"] == 20.0  # service_ms, not latency_ms (99.0)
    assert row["k6"]["p95"] == 18.0
    assert row["diff"] == pytest.approx({"p50": -2.0, "p95": -2.0, "p99": -2.0})
    assert [p["comparable"] for p in pairs] == [True, True, True]


def test_overall_is_mean_over_comparable_pairs(results):
    pairs = compare_session(*load_session(results, "x"))
    row = overall_rows(pairs)["OVERALL"]
    assert row["ours"]["p95"] == pytest.approx(20.0)
    assert row["k6"]["p95"] == pytest.approx(18.5)
    assert row["diff"]["p95"] == pytest.approx(-1.5)


def test_summary_within_tolerance_and_same_sign(results):
    s = summary(compare_session(*load_session(results, "x")), tolerance_ms=5.0)
    assert s["within"] is True
    assert s["sign"] == -1
    assert s["max_abs_p95_diff_ms"] == pytest.approx(2.0)
    assert s["overall_p95_diffs"] == pytest.approx([-2.0, -1.5, -1.0])
    assert (s["k6_higher_endpoints"], s["k6_lower_endpoints"]) == (0, 3)


def test_summary_outside_tolerance_and_mixed_sign(results):
    write(results, "x-k6-run2.json", k6(30.0))
    s = summary(compare_session(*load_session(results, "x")), tolerance_ms=5.0)
    assert s["within"] is False
    assert s["sign"] is None
    assert s["max_abs_p95_diff_ms"] == pytest.approx(9.0)


@pytest.mark.parametrize(
    ("name", "report", "problem"),
    [
        ("x-constant-seed1.json", ours(1, 20.0, exit_code=2), "ours INVALID"),
        ("x-constant-seed1.json", ours(1, 20.0, suspensions=[{"in_run": False}]), "ours suspension"),
        ("x-k6-run1.json", k6(18.0, dropped=3), "k6 dropped_iterations 3"),
    ],
)
def test_pair_not_comparable(results, name, report, problem):
    write(results, name, report)
    pairs = compare_session(*load_session(results, "x"))
    assert pairs[0]["comparable"] is False
    assert pairs[0]["problems"] == [problem]
    s = summary(pairs, tolerance_ms=5.0)
    assert s["comparable"] == 2
    assert s["overall_p95_diffs"] == pytest.approx([-1.5, -1.0])


def test_errors_are_counted_on_both_sides(results):
    write(results, "x-constant-seed2.json", ours(2, 21.0, errors=1))
    write(results, "x-k6-run3.json", k6(18.0, errors=4))
    pairs = compare_session(*load_session(results, "x"))
    assert pairs[1]["endpoints"]["OVERALL"]["ours"]["errors"] == 1
    assert pairs[2]["endpoints"]["OVERALL"]["k6"]["errors"] == 4
    s = summary(pairs, tolerance_ms=5.0)
    assert (s["errors_ours"], s["errors_k6"]) == (1, 4)
    # Errors are reported, not a reason to call a pair not comparable.
    assert s["comparable"] == 3


def test_unpaired_run_is_left_out(results):
    (results / "x-k6-run3.json").unlink()
    pairs = compare_session(*load_session(results, "x"))
    assert [p["n"] for p in pairs] == [1, 2]


def test_main_prints_pairs_and_summary(results, capsys):
    code = main(["--prefix", "x", "--results-dir", str(results)])
    out = capsys.readouterr().out
    assert code == 0
    assert "k6: k6 v2.3.0 (test)" in out
    assert "Pair 1: ours constant seed 1 vs k6 run 1 - comparable" in out
    assert "all within 5 ms: yes" in out
    assert "same sign in all: yes (k6 lower)" in out


def test_main_not_comparable_and_outside_tolerance(results, capsys):
    write(results, "x-k6-run1.json", k6(18.0, dropped=2))
    write(results, "x-k6-run2.json", k6(40.0))
    code = main(["--prefix", "x", "--results-dir", str(results)])
    out = capsys.readouterr().out
    assert code == 1
    assert "NOT COMPARABLE: k6 dropped_iterations 2" in out
    assert "all within 5 ms: no" in out


def test_main_without_pairs(tmp_path, capsys):
    assert main(["--prefix", "nothing", "--results-dir", str(tmp_path)]) == 1
