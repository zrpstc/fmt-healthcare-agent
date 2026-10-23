#!/usr/bin/env bash
# Activate the tested knowledge UI without restarting pipelines or Elasticsearch.
set -euo pipefail
if (( EUID != 0 )); then
  echo "The current API/Web processes run as root. Run: sudo bash deploy/activate-knowledge-ui.sh" >&2
  exit 2
fi
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
WEB="$ROOT/apps/workspace-web"
BACKUP="$ROOT/tmp/knowledge-ui-20261023/production-build-$(date +%Y%m%dT%H%M%S)"
unset WGS_WEB_DIST_DIR
[[ -f "$WEB/.next-knowledge/BUILD_ID" ]] || { echo "Tested staging build is missing." >&2; exit 2; }
umask 077

stop_service() {
  local name="$1" pid_file="$DATA_ROOT/run/$1.pid" pid cwd command
  [[ -f "$pid_file" ]] || return 0
  pid="$(cat "$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ ]] || { echo "Invalid PID for $name" >&2; return 2; }
  kill -0 "$pid" 2>/dev/null || return 0
  cwd="$(readlink -f "/proc/$pid/cwd")"
  command="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  [[ "$cwd" == "$ROOT" || "$cwd" == "$WEB" ]] || { echo "Refusing unrelated process $pid" >&2; return 2; }
  if [[ "$name" == workspace-api ]]; then
    [[ "$command" == *"uvicorn app.main:app"* && "$command" == *"--port $WGS_API_PORT"* ]] || return 2
  else
    [[ "$command" == *"next-server"* || "$command" == *"next start"* ]] || return 2
  fi
  kill -TERM "$pid"
  for ((i=0; i<100; i++)); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep .2
  done
  echo "$name has not exited; activation stopped." >&2
  return 2
}

start_web() {
  nohup "$WEB/node_modules/.bin/next" start "$WEB" -p "$WGS_WEB_PORT" -H "$WGS_WEB_HOST" >>"$DATA_ROOT/logs/workspace-web.log" 2>&1 </dev/null &
  echo "$!" > "$DATA_ROOT/run/workspace-web.pid"
}

stop_service workspace-web
if [[ -d "$WEB/.next" ]]; then
  [[ ! -L "$WEB/.next" ]] || { echo "Unexpected build symlink" >&2; exit 2; }
  mv -- "$WEB/.next" "$BACKUP"
fi
if ! (cd "$WEB" && NEXT_TELEMETRY_DISABLED=1 npm run build); then
  [[ ! -d "$WEB/.next" ]] || mv -- "$WEB/.next" "$BACKUP.failed"
  [[ ! -d "$BACKUP" ]] || mv -- "$BACKUP" "$WEB/.next"
  start_web
  echo "Build failed; the previous Web build has been restored. API was left running." >&2
  exit 1
fi
stop_service workspace-api
nohup "$WGS_ENV_ROOT/bin/python" -m uvicorn app.main:app --app-dir "$ROOT/apps/workspace-api" --host 127.0.0.1 --port "$WGS_API_PORT" >>"$DATA_ROOT/logs/workspace-api.log" 2>&1 </dev/null &
echo "$!" > "$DATA_ROOT/run/workspace-api.pid"
start_web
"$WGS_ENV_ROOT/bin/python" - "$WGS_API_PORT" "$WGS_WEB_PORT" <<'PY'
import sys
import time
import httpx
for port, path in [(sys.argv[1], '/api/samples'), (sys.argv[2], '/knowledge')]:
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
echo "Knowledge UI activated. Previous Web build: $BACKUP"
