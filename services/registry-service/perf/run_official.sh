#!/usr/bin/env bash
# Official NFR-1.1 measurement: 4 runs against a freshly seeded service, with
# system monitors recorded alongside. Run it from a plain terminal, VS Code closed:
#   cd services/registry-service && bash perf/run_official.sh
# Dry run: WARMUP=2 DURATION=10 RESULTS_PREFIX=dry bash perf/run_official.sh

set -euo pipefail

cd "$(dirname "$0")/.."

WARMUP="${WARMUP:-20}"
DURATION="${DURATION:-300}"
RESULTS_PREFIX="${RESULTS_PREFIX:-official}"
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
RUNS=("poisson 1" "poisson 2" "poisson 3" "constant 1")
NAMES=()
CODES=()
for run in "${RUNS[@]}"; do
  read -r arrival seed <<< "$run"
  name="$RESULTS_PREFIX-$arrival-seed$seed"
  section "Run $name (warm-up ${WARMUP} s, duration ${DURATION} s)"
  # A failed or INVALID run is recorded, not fatal: the remaining runs still happen.
  set +e
  uv run python perf/load_test.py --arrival "$arrival" --seed "$seed" \
    --warmup "$WARMUP" --duration "$DURATION" --out "$RESULTS/$name.json" \
    | tee "$RESULTS/$name.txt"
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
import json, sys
path, name, code = sys.argv[1:]
try:
    report = json.load(open(path))
except (OSError, ValueError):
    print(f"{name:<32} exit {code:>2}  no report written")
    sys.exit()
p95 = report["endpoints"]["OVERALL"]["latency_ms"]["p95"]
lag = report["checks"]["generator_lag"]["p99_ms"]
result = report["verdict"]
verdict = "PASS" if result["passed"] else ("INVALID" if result["exit_code"] == 2 else "FAIL")
fmt = lambda v: "-" if v is None else f"{v:.1f}"
print(f"{name:<32} exit {code:>2}  overall p95 {fmt(p95):>8} ms  lag p99 {fmt(lag):>7} ms  {verdict}")
EOF
done
elapsed=$((SECONDS - START_SECONDS))
printf 'Total time: %dm %02ds\n' $((elapsed / 60)) $((elapsed % 60))
echo "Results: $RESULTS/$RESULTS_PREFIX-*"
