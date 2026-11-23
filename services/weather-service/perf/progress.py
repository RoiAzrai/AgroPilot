"""Progress arithmetic and phase log for the measurement session (design 5.11).

Pure functions plus a small log writer; the runner decides when to draw. Progress is
time-based against the plan, so the estimates for setup, cache warm-up, summary and
zero-calls check are only used for the bar and the ETA.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SEEDS = (1, 2, 3)
BAR_WIDTH = 30
# Estimated seconds for the phases whose length is not set by the options.
SETUP_S = 10.0
CACHE_WARMUP_S = 2.0
SUMMARY_S = 1.0
ZERO_CALLS_S = 1.0
# While the session is not finished the bar stops short of 100 %.
NOT_DONE_MAX = 0.999


@dataclass(frozen=True)
class Phase:
    name: str
    label: str
    seconds: float


def session_plan(warmup: float, duration: float) -> list[Phase]:
    plan = [Phase("setup", "[session]", SETUP_S), Phase("cache warm-up", "[session]", CACHE_WARMUP_S)]
    for i, seed in enumerate(SEEDS, start=1):
        label = f"[run {i}/{len(SEEDS)}] Poisson seed {seed}"
        plan.append(Phase("load warm-up", label, warmup))
        plan.append(Phase("measuring", label, duration))
    plan.append(Phase("summary", "[session]", SUMMARY_S))
    plan.append(Phase("zero-calls check", "[session]", ZERO_CALLS_S))
    return plan


def _total(plan: list[Phase]) -> float:
    return sum(p.seconds for p in plan)


def _done_seconds(plan: list[Phase], phase_index: int, phase_elapsed: float) -> float:
    done = sum(p.seconds for p in plan[:phase_index])
    if phase_index < len(plan):
        done += min(max(phase_elapsed, 0.0), plan[phase_index].seconds)
    return done


def overall_fraction(plan: list[Phase], phase_index: int, phase_elapsed: float) -> float:
    """0..1; exactly 1.0 only once phase_index is past the last phase."""
    if phase_index >= len(plan):
        return 1.0
    total = _total(plan)
    if total <= 0:
        return 0.0
    return min(_done_seconds(plan, phase_index, phase_elapsed) / total, NOT_DONE_MAX)


def eta_seconds(plan: list[Phase], phase_index: int, phase_elapsed: float) -> float:
    return max(_total(plan) - _done_seconds(plan, phase_index, phase_elapsed), 0.0)


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def status_line(plan: list[Phase], phase_index: int, phase_elapsed: float, total_elapsed: float) -> str:
    fraction = overall_fraction(plan, phase_index, phase_elapsed)
    filled = int(fraction * BAR_WIDTH)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    percent = int(fraction * 100)
    eta = eta_seconds(plan, phase_index, phase_elapsed)
    if phase_index >= len(plan):
        what = "done"
    else:
        phase = plan[phase_index]
        shown = int(min(max(phase_elapsed, 0.0), phase.seconds))
        what = f"{phase.label} - {phase.name} ({shown}/{int(phase.seconds)} s)"
    return f"[{bar}] {percent:3d}% elapsed {_clock(total_elapsed)} ETA {_clock(eta)} | {what}"


class PhaseLog:
    """Appends '<ISO timestamp> <label> - <name>' for every phase change."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def log(self, phase: Phase) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.path.open("a") as out:
            out.write(f"{stamp} {phase.label} - {phase.name}\n")
