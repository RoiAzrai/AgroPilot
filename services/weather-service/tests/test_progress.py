"""Progress display for the measurement session (design 5.11)."""

from perf.progress import (
    PhaseLog, eta_seconds, overall_fraction, session_plan, status_line,
)

PLAN = session_plan(warmup=20, duration=300)


def test_plan_phases():
    names = [p.name for p in PLAN]
    assert names[:2] == ["setup", "cache warm-up"]
    assert names[2:4] == ["load warm-up", "measuring"]
    assert names[-2:] == ["summary", "zero-calls check"]
    assert PLAN[6].label == "[run 3/3] Poisson seed 3"
    assert PLAN[3].seconds == 300 and PLAN[2].seconds == 20


def test_fraction_monotone_and_complete():
    last = 0.0
    for index, phase in enumerate(PLAN):
        for step in range(0, int(phase.seconds) + 1, 5):
            value = overall_fraction(PLAN, index, step)
            assert last <= value < 1.0
            last = value
        # Overrunning a phase never goes backwards or reaches 100 % early.
        assert last <= overall_fraction(PLAN, index, phase.seconds * 3) < 1.0
        last = overall_fraction(PLAN, index, phase.seconds * 3)
    assert overall_fraction(PLAN, len(PLAN), 0) == 1.0


def test_eta_zero_at_end():
    assert eta_seconds(PLAN, len(PLAN), 0) == 0
    assert eta_seconds(PLAN, 0, 0) > eta_seconds(PLAN, 3, 100) > 0


def test_status_line_example():
    # Run 2: load warm-up is index 4, measuring index 5.
    line = status_line(PLAN, 5, 180, 500)
    assert "[run 2/3] Poisson seed 2 - measuring (180/300 s)" in line
    assert "%" in line and "ETA" in line and "08:20" in line


def test_status_line_done():
    assert "100%" in status_line(PLAN, len(PLAN), 0, 1000)


def test_phase_log_lines(tmp_path):
    path = tmp_path / "x-phases.log"
    log = PhaseLog(path)
    for phase in PLAN:
        log.log(phase)
    lines = path.read_text().splitlines()
    assert len(lines) == len(PLAN)
    for line, phase in zip(lines, PLAN):
        stamp, rest = line.split(" ", 1)
        assert "T" in stamp and rest == f"{phase.label} - {phase.name}"
