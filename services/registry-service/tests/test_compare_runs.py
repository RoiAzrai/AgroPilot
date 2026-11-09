import json

import pytest

from perf.compare_runs import (
    load_session,
    main,
    official_result,
    pair_summary,
    paired_rows,
)


def report(arrival, seed, p95, ci, exit_code=0, suspensions=(), endpoint_p95=None):
    """A minimal load_test.py report, with the fields compare_runs.py reads."""
    rows = {
        "farms_list": {"latency_ms": {"p95": endpoint_p95 or p95, "p95_ci": ci}},
        "OVERALL": {"latency_ms": {"p95": p95, "p95_ci": ci}},
    }
    return {
        "metadata": {"arrival": arrival, "seed": seed},
        "endpoints": rows,
        "suspensions": list(suspensions),
        "verdict": {"exit_code": exit_code, "passed": exit_code == 0, "reasons": []},
    }


def write_session(directory, prefix, reports):
    for r in reports:
        meta = r["metadata"]
        path = directory / f"{prefix}-{meta['arrival']}-seed{meta['seed']}.json"
        path.write_text(json.dumps(r))


@pytest.fixture
def session(tmp_path):
    write_session(tmp_path, "paired", [
        report("poisson", 1, 18.0, [17.0, 19.5], endpoint_p95=21.0),
        report("constant", 1, 16.0, [15.5, 16.8]),
        report("poisson", 2, 17.5, [16.5, 18.6], endpoint_p95=24.0),
        report("constant", 2, 17.0, [16.2, 17.9]),
        report("poisson", 3, 19.0, [18.0, 20.1]),
        report("constant", 3, 15.0, [14.4, 15.8]),
    ])
    write_session(tmp_path, "official", [report("poisson", 1, 99.0, [98.0, 99.5])])
    return load_session(tmp_path, "paired")


def test_load_session_reads_only_the_prefix(session):
    assert sorted(session) == [
        ("constant", 1), ("constant", 2), ("constant", 3),
        ("poisson", 1), ("poisson", 2), ("poisson", 3),
    ]
    assert session[("poisson", 1)]["endpoints"]["OVERALL"]["latency_ms"]["p95"] == 18.0


def test_official_result_pass_and_worst(session):
    official = official_result(session)
    assert official["passed"] is True
    assert official["seeds"] == [1, 2, 3]
    assert official["worst"] == {"p95": 24.0, "endpoint": "farms_list", "seed": 2}


def test_official_result_fails_when_a_poisson_run_failed(session):
    session[("poisson", 2)] = report("poisson", 2, 120.0, [110.0, 130.0], exit_code=1)
    official = official_result(session)
    assert official["passed"] is False
    assert official["failed_seeds"] == [2]


def test_official_result_without_poisson_runs_fails():
    assert official_result({("constant", 1): report("constant", 1, 10.0, [9.0, 11.0])})["passed"] is False


def test_paired_rows_difference_and_overlap(session):
    rows = paired_rows(session)
    assert [row["seed"] for row in rows] == [1, 2, 3]
    assert [row["difference_ms"] for row in rows] == pytest.approx([2.0, 0.5, 4.0])
    assert [row["ci_overlap"] for row in rows] == [False, True, False]
    assert all(row["comparable"] for row in rows)


@pytest.mark.parametrize(
    ("constant", "reason"),
    [
        (report("constant", 1, 16.0, [15.5, 16.8], exit_code=2), "constant INVALID"),
        (report("constant", 1, 16.0, [15.5, 16.8], suspensions=[{"in_run": False}]), "constant suspension"),
    ],
)
def test_pair_not_comparable(session, constant, reason):
    session[("constant", 1)] = constant
    row = paired_rows(session)[0]
    assert row["comparable"] is False
    assert row["reasons"] == [reason]


def test_pair_summary_same_sign_and_overlaps(session):
    summary = pair_summary(paired_rows(session))
    assert summary == {"comparable": 3, "same_sign": True, "sign": 1, "ci_overlaps": 1}


def test_pair_summary_mixed_sign(session):
    session[("constant", 2)] = report("constant", 2, 18.0, [17.1, 18.9])
    summary = pair_summary(paired_rows(session))
    assert summary["same_sign"] is False
    assert summary["sign"] is None


def test_pair_summary_ignores_pairs_that_are_not_comparable(session):
    session[("constant", 2)] = report("constant", 2, 18.0, [17.1, 18.9], exit_code=2)
    summary = pair_summary(paired_rows(session))
    assert summary["comparable"] == 2
    assert summary["same_sign"] is True


def test_main_prints_both_sections(tmp_path, session, capsys):
    write_session(tmp_path, "paired2", [r for r in session.values()])
    code = main(["--prefix", "paired2", "--results-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Official NFR-1.1 result" in out
    assert "Worst p95: 24.0 ms (farms_list, Poisson seed 2)" in out
    assert "18.0 [17.0, 19.5]" in out
    assert "same sign in all: yes (Poisson higher)" in out
    assert "CIs overlap in 1 of 3" in out


def test_main_without_reports(tmp_path, capsys):
    assert main(["--prefix", "nothing", "--results-dir", str(tmp_path)]) == 1


DRAIN = (
    "run\tdrain_s\tprobes\trestarted\tstatus\n"
    "paired2-poisson-seed1\t0.4\t2\tno\tdrained\n"
    "paired2-constant-seed1\t612.3\t9\tyes\tdrained\n"
)


def test_main_prints_the_drain_record(tmp_path, session, capsys):
    write_session(tmp_path, "paired2", list(session.values()))
    (tmp_path / "paired2-drain.txt").write_text(DRAIN)
    main(["--prefix", "paired2", "--results-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Drain before each run" in out
    assert "paired2-constant-seed1             612.3 s  probes   9  restart yes  drained" in out
    assert "restarts: 1; not drained: 0" in out


def test_main_without_a_drain_record(tmp_path, session, capsys):
    write_session(tmp_path, "paired2", list(session.values()))
    main(["--prefix", "paired2", "--results-dir", str(tmp_path)])
    assert "no drain record for this session" in capsys.readouterr().out
