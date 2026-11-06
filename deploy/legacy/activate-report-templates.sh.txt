#!/usr/bin/env bash
# Activate report body/API and TOC anchors without stopping workers or search.
set -euo pipefail
if (( EUID != 0 )); then
  echo "API/Web run as root. Run: sudo bash deploy/activate-report-templates.sh" >&2
  exit 2
fi
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
WEB="$ROOT/apps/workspace-web"
WEB_BUILD_DIR="${WGS_WEB_DIST_DIR:-.next}"
[[ "$WEB_BUILD_DIR" =~ ^\.next([.-][A-Za-z0-9_-]+)?$ ]] || { echo "Unexpected Web build path" >&2; exit 2; }
[[ ! -L "$WEB/$WEB_BUILD_DIR" ]] || { echo "Unexpected build symlink" >&2; exit 2; }
[[ -f "$ROOT/tmp/report-word-rework-20261024/apps/workspace-web/.next/BUILD_ID" ]] || {
  echo "Verified staging build is missing; no services changed." >&2; exit 2;
}
BACKUP_ROOT="$ROOT/tmp/report-template-activation-$(date +%Y%m%dT%H%M%S)"
umask 077
mkdir -p "$BACKUP_ROOT"

stop_web() {
  local pid_file="$DATA_ROOT/run/workspace-web.pid" pid cwd command state
  [[ -r "$pid_file" ]] || { echo "Missing Web PID file" >&2; return 2; }
  pid="$(cat "$pid_file")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid Web PID" >&2; return 2; }
  [[ -d "/proc/$pid" ]] || return 0
  cwd="$(readlink -f "/proc/$pid/cwd")"
  command="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  [[ "$cwd" == "$ROOT" || "$cwd" == "$WEB" ]] || { echo "Web PID has unrelated cwd" >&2; return 2; }
  [[ "$command" == *next-server* || "$command" == *"next start"* ]] || { echo "Web PID is unrelated" >&2; return 2; }
  kill -TERM "$pid"
  for ((attempt=0; attempt<100; attempt++)); do
    [[ -d "/proc/$pid" ]] || return 0
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    [[ "$state" == Z ]] && return 0
    sleep .2
  done
  echo "Web did not stop; no build was replaced." >&2
  return 2
}

start_web() {
  nohup "$WEB/node_modules/.bin/next" start "$WEB" -p "$WGS_WEB_PORT" -H "$WGS_WEB_HOST" \
    >>"$DATA_ROOT/logs/workspace-web.log" 2>&1 </dev/null &
  echo "$!" > "$DATA_ROOT/run/workspace-web.pid"
}

stop_web
if [[ -d "$WEB/$WEB_BUILD_DIR" ]]; then
  mv -- "$WEB/$WEB_BUILD_DIR" "$BACKUP_ROOT/previous-build"
fi
if ! (cd "$WEB" && NEXT_TELEMETRY_DISABLED=1 npm run build); then
  [[ ! -d "$WEB/$WEB_BUILD_DIR" ]] || mv -- "$WEB/$WEB_BUILD_DIR" "$BACKUP_ROOT/failed-build"
  [[ ! -d "$BACKUP_ROOT/previous-build" ]] || mv -- "$BACKUP_ROOT/previous-build" "$WEB/$WEB_BUILD_DIR"
  start_web
  echo "Build failed; restored the previous Web build. API was left running." >&2
  exit 1
fi
# Always restore the Web listener even if the backend restart needs attention.
if ! bash "$ROOT/deploy/restart-report-api.sh"; then
  start_web
  echo "API restart failed; Web was started. Inspect the API log." >&2
  exit 1
fi
start_web
"$WGS_ENV_ROOT/bin/python" - "$WGS_API_PORT" "$WGS_WEB_PORT" <<'PY'
import sys
import time
import httpx
for port, path in [(sys.argv[1], '/health'), (sys.argv[2], '/reports')]:
    for attempt in range(30):
        try:
            response = httpx.get(f'http://127.0.0.1:{port}{path}', timeout=5)
            response.raise_for_status()
            print(f'OK {port}{path}: {response.status_code}')
            break
        except httpx.HTTPError:
            time.sleep(1)
    else:
        raise SystemExit(f'Service {port} did not become healthy; inspect var/logs.')
PY
echo "Report templates activated. Previous Web build: $BACKUP_ROOT/previous-build"
echo "Existing report files are preserved; regenerate a report to apply the new body."
