#!/usr/bin/env bash
# AgroPilot production deploy. Runs ON the EC2 server as user "ubuntu".
#
#   deploy.sh <40-char commit sha>   deploy that commit (rolls back on failure)
#   deploy.sh --preflight            only check the server, change nothing
#
# Exit codes:
#   0  deployed, all services healthy
#   1  deploy failed, rolled back, server healthy on the last known good commit
#   2  deploy failed and the rollback did not work either: manual action needed
#   3  refused before changing anything (bad input, another deploy running, preflight)
set -euo pipefail

APP=/home/ubuntu/AgroPilot
SVC=$APP/services
UV=/home/ubuntu/.local/bin/uv
STATE=/home/ubuntu/.agropilot-deploy
LAST_GOOD=$STATE/last-good-sha
HISTORY=$STATE/history.log
LOCK=$STATE/deploy.lock
UNITS=(registry weather planner frontend)   # restart order
SHA=""
ATTEMPT_RC=0

log() { printf '%s [deploy] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
refuse() { log "REFUSED: $*"; exit 3; }
record() { printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$1" "$2" >> "$HISTORY"; }
sanitize() { sed -E 's#(://[^:/@[:space:]]+:)[^@[:space:]]+@#\1***@#g'; }

preflight() {
  local problems=() cmd unit f avail p key
  for cmd in git curl flock node npm sudo; do
    command -v "$cmd" >/dev/null 2>&1 || problems+=("missing command: $cmd")
  done
  [[ -x $UV ]] || problems+=("missing uv at $UV")
  [[ -d $APP/.git ]] || problems+=("no git repository at $APP")
  for f in "$SVC/registry-service/.env" "$SVC/weather-service/.env" \
           "$SVC/planner-service/.env" "$SVC/frontend/.env.local"; do
    [[ -f $f ]] || problems+=("missing config file: $f")
  done
  # Required by registry-service for plot photos: without them it does not start.
  for key in AWS_S3_BUCKET AWS_REGION; do
    grep -Eq "^${key}=.+" "$SVC/registry-service/.env" 2>/dev/null \
      || problems+=("missing $key in $SVC/registry-service/.env")
  done
  sudo -n true 2>/dev/null || problems+=("sudo needs a password")
  for unit in "${UNITS[@]}"; do
    systemctl cat "$unit.service" >/dev/null 2>&1 || problems+=("missing systemd unit: $unit.service")
  done
  systemctl is-active --quiet postgresql || problems+=("postgresql is not active")
  avail=$(df -Pm "$APP" 2>/dev/null | awk 'NR==2 {print $4}' || true)
  if [[ -z $avail ]] || (( avail < 1500 )); then
    problems+=("low disk space: ${avail:-unknown} MB free, need 1500 MB")
  fi
  if (( ${#problems[@]} > 0 )); then
    for p in "${problems[@]}"; do log "preflight problem: $p"; done
    refuse "preflight failed (nothing was changed)"
  fi
  log "preflight OK"
}

retry() {   # retry <attempts> <command...>
  local n=$1 i
  shift
  for ((i = 1; i <= n; i++)); do
    if "$@"; then return 0; fi
    log "attempt $i/$n failed: $*"
    sleep $((i * 3))
  done
  return 1
}

fetch_and_check() {
  retry 3 git -C "$APP" fetch --prune origin main || refuse "git fetch failed"
  git -C "$APP" cat-file -e "$SHA^{commit}" 2>/dev/null || refuse "commit $SHA not found"
  git -C "$APP" merge-base --is-ancestor "$SHA" origin/main || refuse "commit $SHA is not on origin/main"
  if [[ -n $(git -C "$APP" status --porcelain --untracked-files=no) ]]; then
    log "WARNING: tracked files were changed by hand on the server; they will be overwritten:"
    git -C "$APP" status --short --untracked-files=no
  fi
}

rollback_target() {   # rollback_target <currently-checked-out-sha>
  local prev=$1 good=""
  if [[ -f $LAST_GOOD ]]; then good=$(<"$LAST_GOOD"); fi
  if [[ $good =~ ^[0-9a-f]{40}$ ]] && git -C "$APP" cat-file -e "$good^{commit}" 2>/dev/null; then
    echo "$good"
  else
    echo "$prev"
  fi
}

sync_python() {
  local d
  for d in registry-service weather-service planner-service; do
    log "uv sync: $d"
    (cd "$SVC/$d" && "$UV" sync --locked)
  done
}

build_frontend() {   # build_frontend <sha>
  local sha=$1 fe=$SVC/frontend lock_hash tree_hash need_install=0 need_build=0
  lock_hash=$(git -C "$APP" rev-parse "$sha:services/frontend/package-lock.json")
  tree_hash=$(git -C "$APP" rev-parse "$sha:services/frontend")
  cd "$fe"
  [[ -d node_modules && -f node_modules/.agropilot-lock && $(<node_modules/.agropilot-lock) == "$lock_hash" ]] || need_install=1
  [[ -f .next/BUILD_ID && -f .next/.agropilot-tree && $(<.next/.agropilot-tree) == "$tree_hash" ]] || need_build=1
  if (( need_install )); then need_build=1; fi
  if (( need_install || need_build )); then
    log "frontend: stopping the service while dependencies or the build change"
    sudo systemctl stop frontend.service
  fi
  if (( need_install )); then
    log "frontend: npm ci"
    npm ci --no-audit --no-fund
    echo "$lock_hash" > node_modules/.agropilot-lock
  fi
  if (( need_build )); then
    log "frontend: npm run build"
    rm -f .next/.agropilot-tree
    NEXT_TELEMETRY_DISABLED=1 npm run build
    echo "$tree_hash" > .next/.agropilot-tree
  else
    log "frontend: build is up to date, skipping"
  fi
}

restart_all() {
  local u
  sudo systemctl reset-failed "${UNITS[@]/%/.service}" 2>/dev/null || true
  for u in "${UNITS[@]}"; do
    log "restarting $u"
    sudo systemctl restart "$u.service"
  done
}

http_code() { curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null || true; }

wait_for_200() {   # wait_for_200 <name> <url>
  local name=$1 url=$2 i code=000
  for ((i = 1; i <= 30; i++)); do
    code=$(http_code "$url")
    if [[ $code == 200 ]]; then
      log "healthy: $name"
      return 0
    fi
    sleep 2
  done
  log "UNHEALTHY: $name ($url), last HTTP code: $code"
  return 1
}

verify_all() {
  wait_for_200 "registry" "http://127.0.0.1:8000/health"
  wait_for_200 "registry database (GET /v1/farms)" "http://127.0.0.1:8000/v1/farms"
  wait_for_200 "weather" "http://127.0.0.1:8001/health"
  wait_for_200 "planner" "http://127.0.0.1:8002/health"
  wait_for_200 "frontend" "http://127.0.0.1:3000/"
  log "soak test: 10 seconds, looking for crash loops"
  sleep 10
  local u state restarts
  for u in "${UNITS[@]}"; do
    state=$(systemctl is-active "$u.service" || true)
    restarts=$(systemctl show -p NRestarts --value "$u.service" 2>/dev/null || echo 0)
    if [[ $state != active || ${restarts:-0} != 0 ]]; then
      log "UNSTABLE: $u (state=$state, restarts=$restarts)"
      return 1
    fi
  done
  log "all services healthy and stable"
}

dump_diagnostics() {
  local u state
  for u in "${UNITS[@]}"; do
    state=$(systemctl is-active "$u.service" || true)
    log "---- $u (state: $state), last 15 log lines ----"
    sudo journalctl -u "$u.service" -n 15 --no-pager 2>&1 | sanitize || true
  done
}

deploy_release() {   # runs in a subshell with "set -e": the first failure stops it
  local sha=$1
  log "checking out $sha"
  git -C "$APP" reset --hard "$sha"
  sync_python
  build_frontend "$sha"
  restart_all
  verify_all
}

attempt() {   # attempt <sha>: sets ATTEMPT_RC and never aborts the script
  set +e
  ( set -e; deploy_release "$1" )
  ATTEMPT_RC=$?
  set -e
}

main() {
  if [[ ${1:-} == --preflight ]]; then
    preflight
    log "preflight only: the server is ready, nothing was changed"
    return 0
  fi
  SHA=${1:-}
  [[ $SHA =~ ^[0-9a-f]{40}$ ]] || refuse "usage: deploy.sh <40-char commit sha> | --preflight"
  mkdir -p "$STATE"
  chmod 700 "$STATE"
  exec 9>"$LOCK"
  flock -n 9 || refuse "another deploy is already running"

  log "deploying $SHA"
  preflight
  fetch_and_check

  local prev target
  prev=$(git -C "$APP" rev-parse HEAD)
  target=$(rollback_target "$prev")
  log "currently on $prev, rollback target is $target"

  attempt "$SHA"
  if (( ATTEMPT_RC == 0 )); then
    echo "$SHA" > "$LAST_GOOD"
    record "$SHA" deployed
    log "SUCCESS: $SHA is live and healthy"
    return 0
  fi

  log "DEPLOY FAILED (code $ATTEMPT_RC)"
  dump_diagnostics
  if [[ $target == "$SHA" ]]; then
    record "$SHA" failed-no-rollback-target
    log "NO ROLLBACK POSSIBLE: the last known good commit is the one that just failed. Manual action needed."
    exit 2
  fi

  log "ROLLING BACK to $target"
  attempt "$target"
  if (( ATTEMPT_RC == 0 )); then
    echo "$target" > "$LAST_GOOD"
    record "$SHA" "failed-rolled-back-to-$target"
    log "ROLLED BACK: the server is healthy on $target. The deploy of $SHA FAILED (this job is red on purpose)."
    exit 1
  fi
  dump_diagnostics
  record "$SHA" "failed-rollback-failed"
  log "ROLLBACK FAILED: manual action needed on the server."
  exit 2
}

main "$@"
