#!/usr/bin/env bash
# Cross-check of load_test.py against k6: three adjacent pairs, our tool at a
# constant rate (seeds 1-3) then k6 (perf/k6_mix.js), against a freshly seeded
# service, with system monitors recorded alongside, then perf/compare_k6.py.
# Run it from a plain terminal, VS Code closed:
#   cd services/registry-service && bash perf/run_k6_crosscheck.sh
# Dry run: WARMUP=2 DURATION=10 ASSUME_YES=1 RESULTS_PREFIX=k6dry bash perf/run_k6_crosscheck.sh

set -euo pipefail

cd "$(dirname "$0")/.."

WARMUP="${WARMUP:-20}"
DURATION="${DURATION:-300}"
RESULTS_PREFIX="${RESULTS_PREFIX:-k6cross}"
ASSUME_YES="${ASSUME_YES:-0}"
RESULTS=perf/results
BASE_URL=http://127.0.0.1:8000

SERVER_PID=""
MONITOR_PIDS=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${MONITOR_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  if [[ -n "$SERVER_PID" ]]; then
    # The server runs in its own process group: stop uv and uvicorn together.
    kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'echo; echo "Interrupted."; exit 130' INT TERM

section() { printf '\n=== %s\n' "$*"; }

# --- Pre-flight -------------------------------------------------------------------
section "Pre-flight"
# Never overwrite an earlier session (official-*, paired-*, an earlier k6 session...).
if compgen -G "$RESULTS/$RESULTS_PREFIX-*" >/dev/null; then
  echo "FAIL: $RESULTS/$RESULTS_PREFIX-* already exists. Choose another RESULTS_PREFIX." >&2
  exit 1
fi
echo "OK: no earlier $RESULTS_PREFIX-* results to overwrite."

if ! command -v k6 >/dev/null; then
  echo "FAIL: k6 is not installed (expected in PATH, e.g. ~/.local/bin/k6)." >&2
  exit 1
fi
K6_VERSION="$(k6 version 2>/dev/null | head -n 1)"
echo "OK: $(command -v k6): $K6_VERSION"

if pgrep -f vscode-server >/dev/null; then
  echo "WARNING: $(pgrep -fc vscode-server) VS Code server processes are running in this VM."
  echo "         Close VS Code for the official measurement."
else
  echo "OK: no VS Code server processes."
fi
echo "Top 5 CPU consumers right now (top, 1 s sample):"
top -b -n 2 -d 1 -o %CPU -w 120 | awk '/^top -/ { block++ } block == 2' | sed -n '7,12p'

if ss -ltn | grep -q ':8000 '; then
  echo "FAIL: port 8000 is already in use. Stop whatever is listening there first." >&2
  exit 1
fi
echo "OK: port 8000 is free."

cat <<'EOF'

Before you start, on Windows:
  - Settings > System > Power & battery > Screen and sleep: all four options set to Never.
  - Laptop on power, lid open, power mode on best performance.
  - Games and other heavy apps closed; Task Manager shows idle CPU under 10%.
  - Do not use the computer until the summary prints (about 35 minutes).
EOF
if [[ "$ASSUME_YES" == "1" ]]; then
  echo "ASSUME_YES=1: skipping the confirmation."
elif ! read -r -p "Press Enter to start, or Ctrl+C to abort. " _; then
  echo "FAIL: no confirmation (stdin closed). Set ASSUME_YES=1 for an unattended dry run." >&2
  exit 1
fi

mkdir -p "$RESULTS"
START_SECONDS=$SECONDS

# --- Server -----------------------------------------------------------------------
section "Seed and start the server"
bash seed_registry.sh
setsid uv run uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning \
  > "$RESULTS/$RESULTS_PREFIX-server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$BASE_URL/health" 2>/dev/null; then
    break
  fi
  sleep 0.5
done
if ! curl -fsS -o /dev/null "$BASE_URL/health" 2>/dev/null; then
  echo "FAIL: /health did not answer within 30 s. See $RESULTS/$RESULTS_PREFIX-server.log" >&2
  exit 1
fi
echo "Server is up (pid $SERVER_PID)."

# --- Monitors ---------------------------------------------------------------------
section "Start monitors"
{ date '+%F %T %Z'; free -m; } > "$RESULTS/$RESULTS_PREFIX-free-before.txt"
vmstat -t -w 1 > "$RESULTS/$RESULTS_PREFIX-vmstat.txt" &
MONITOR_PIDS+=($!)
top -b -d 5 -o %CPU -w 200 > "$RESULTS/$RESULTS_PREFIX-top.txt" &
MONITOR_PIDS+=($!)
echo "vmstat and top write to $RESULTS/$RESULTS_PREFIX-{vmstat,top}.txt"

# --- Runs -------------------------------------------------------------------------
# Adjacent pairs: our constant-rate run, then k6, back to back, so both tools see
# the machine in as similar a state as possible. k6 has no seed: "run N" is only
# the pair number, it does not reproduce our seed N's requests.
RUNS=("ours 1" "k6 1" "ours 2" "k6 2" "ours 3" "k6 3")
NAMES=()
CODES=()
for run in "${RUNS[@]}"; do
  read -r tool n <<< "$run"
  if [[ "$tool" == "ours" ]]; then
    name="$RESULTS_PREFIX-constant-seed$n"
  else
    name="$RESULTS_PREFIX-k6-run$n"
  fi
  section "Run $name (warm-up ${WARMUP} s, duration ${DURATION} s)"
  # A failed or INVALID run is recorded, not fatal: the remaining runs still happen.
  set +e
  if [[ "$tool" == "ours" ]]; then
    uv run python perf/load_test.py --arrival constant --seed "$n" \
      --warmup "$WARMUP" --duration "$DURATION" --out "$RESULTS/$name.json" \
      | tee "$RESULTS/$name.txt"
  else
    # stdout: the per-endpoint summary from handleSummary; stderr (k6 log lines and
    # one "request_error ..." line per failed request) goes to <name>.log.
    k6 run --quiet --no-usage-report \
      -e BASE_URL="$BASE_URL" -e WARMUP="$WARMUP" -e DURATION="$DURATION" \
      -e SUMMARY_OUT="$RESULTS/$name.json" -e K6_VERSION="$K6_VERSION" \
      perf/k6_mix.js 2> "$RESULTS/$name.log" | tee "$RESULTS/$name.txt"
  fi
  code=${PIPESTATUS[0]}
  set -e
  NAMES+=("$name")
  CODES+=("$code")
done

{ date '+%F %T %Z'; free -m; } > "$RESULTS/$RESULTS_PREFIX-free-after.txt"

# --- Summary ----------------------------------------------------------------------
section "Summary"
for i in "${!NAMES[@]}"; do
  python3 -I - "$RESULTS/${NAMES[$i]}.json" "${NAMES[$i]}" "${CODES[$i]}" <<'EOF'
import json, re, sys
from collections import Counter
path, name, code = sys.argv[1:]
try:
    report = json.load(open(path))
except (OSError, ValueError):
    print(f"{name:<32} exit {code:>2}  no report written")
    sys.exit()
fmt = lambda v: "-" if v is None else f"{v:.1f}"
if report.get("tool") == "k6":
    overall = report["endpoints"]["OVERALL"]
    p95 = (overall["http_req_duration_ms"] or {}).get("p95")
    print(f"{name:<32} exit {code:>2}  overall http_req_duration p95 {fmt(p95):>7} ms  "
          f"errors {overall['errors']}  dropped_iterations {report['dropped_iterations']}  "
          f"{'valid' if report['valid'] else 'INVALID'}")
    # Every failed request, from the request_error lines k6_mix.js writes to the log.
    pattern = re.compile(
        r'request_error scenario=(\S+) endpoint=\S+ status=(\S+) error_code=(\S+) error=\\"(.*?)\\""'
    )
    try:
        found = Counter(m.groups() for m in pattern.finditer(open(path[:-5] + ".log").read()))
    except OSError:
        found = Counter()
    for (scenario, status, error_code, message), n in found.most_common():
        print(f"{'':<32}  {n:>5} x {scenario}: status {status}, error_code {error_code}, {message}")
else:
    p95 = report["endpoints"]["OVERALL"]["service_ms"]["p95"]
    lag = report["checks"]["generator_lag"]["p99_ms"]
    suspensions = len(report.get("suspensions", []))
    result = report["verdict"]
    verdict = "PASS" if result["passed"] else ("INVALID" if result["exit_code"] == 2 else "FAIL")
    print(f"{name:<32} exit {code:>2}  overall service p95 {fmt(p95):>8} ms  "
          f"errors {report['endpoints']['OVERALL']['errors']}  lag p99 {fmt(lag):>7} ms  "
          f"suspensions {suspensions}  {verdict}")
EOF
done

section "Cross-check comparison"
set +e
uv run python perf/compare_k6.py --prefix "$RESULTS_PREFIX" | tee "$RESULTS/$RESULTS_PREFIX-comparison.txt"
compare_code=${PIPESTATUS[0]}
set -e
echo "compare_k6.py exit $compare_code (0 = every comparable pair within tolerance)"

elapsed=$((SECONDS - START_SECONDS))
printf 'Total time: %dm %02ds\n' $((elapsed / 60)) $((elapsed % 60))
echo "Results: $RESULTS/$RESULTS_PREFIX-*"
