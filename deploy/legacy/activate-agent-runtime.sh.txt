#!/usr/bin/env bash
# Activate the prebuilt Agent fix; API/Web only. Pipelines and model service stay running.
set -euo pipefail
if (( EUID != 0 )); then
  echo "The production API/Web run as root. Run: sudo bash deploy/activate-agent-runtime.sh" >&2
  exit 2
fi
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
WEB="$ROOT/apps/workspace-web"
STAGING="$ROOT/tmp/agent-runtime-20261024"
CONFIG_DIR="${WGS_AGENT_CONFIG_DIR:-$DATA_ROOT/agent-config}"
[[ "$CONFIG_DIR" == /* ]] || CONFIG_DIR="$ROOT/$CONFIG_DIR"
[[ -f "$WEB/.next-agent-runtime/BUILD_ID" ]] || { echo "Prebuilt Web bundle is missing." >&2; exit 2; }
[[ -f "$STAGING/pre-change-source.tar.gz" ]] || { echo "Source rollback archive is missing." >&2; exit 2; }
umask 077
BACKUP="$STAGING/activation-$(date +%Y%m%dT%H%M%S)"
mkdir -m 700 "$BACKUP"
cp -- "$ROOT/.env" "$BACKUP/env"
cp -- "$CONFIG_DIR/agents.json" "$BACKUP/agents.json"
api_stopped=0
web_stopped=0

stop_service() {
  local name="$1" pid_file="$DATA_ROOT/run/$1.pid" pid cwd command state
  [[ -f "$pid_file" ]] || { echo "Missing PID file for $name" >&2; return 2; }
  pid="$(cat "$pid_file")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 2
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
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    [[ "$state" == Z ]] && return 0
    sleep .2
  done
  echo "$name did not stop; no replacement was started." >&2
  return 2
}

start_api() {
  nohup "$WGS_ENV_ROOT/bin/python" -m uvicorn app.main:app --app-dir "$ROOT/apps/workspace-api" --host 127.0.0.1 --port "$WGS_API_PORT" >>"$DATA_ROOT/logs/workspace-api.log" 2>&1 </dev/null &
  echo "$!" > "$DATA_ROOT/run/workspace-api.pid"
}
start_web() {
  (cd "$WEB" && exec nohup "$WEB/node_modules/.bin/next" start "$WEB" -p "$WGS_WEB_PORT" -H "$WGS_WEB_HOST") >>"$DATA_ROOT/logs/workspace-web.log" 2>&1 </dev/null &
  echo "$!" > "$DATA_ROOT/run/workspace-web.pid"
}

rollback() {
  trap - ERR
  set +e
  echo "Activation failed; restoring the previous source/configuration and Web bundle." >&2
  if (( api_stopped )); then stop_service workspace-api; fi
  if (( web_stopped )); then stop_service workspace-web; fi
  cp -- "$BACKUP/env" "$ROOT/.env"
  cp -- "$BACKUP/agents.json" "$CONFIG_DIR/agents.json"
  tar -xzf "$STAGING/pre-change-source.tar.gz" -C "$ROOT"
  unset WGS_WEB_DIST_DIR
  source "$ROOT/deploy/common.sh"
  if (( api_stopped )); then start_api; fi
  if (( web_stopped )); then start_web; fi
  echo "Rollback attempted. Inspect var/logs/workspace-{api,web}.log. Backup: $BACKUP" >&2
  exit 1
}
trap rollback ERR
stop_service workspace-web
web_stopped=1
stop_service workspace-api
api_stopped=1
PYTHONPATH="$ROOT/apps/workspace-api:$ROOT/src" "$WGS_ENV_ROOT/bin/python" "$ROOT/scripts/upgrade_agent_catalog.py"
"$WGS_ENV_ROOT/bin/python" - "$ROOT/.env" <<'PY'
from pathlib import Path
import re
import sys
p = Path(sys.argv[1])
s = re.sub(r'^WGS_WEB_DIST_DIR=.*\n?', '', p.read_text(), flags=re.M)
p.write_text(s.rstrip() + '\nWGS_WEB_DIST_DIR=.next-agent-runtime\n')
PY
export WGS_WEB_DIST_DIR=.next-agent-runtime
start_api
start_web
"$WGS_ENV_ROOT/bin/python" - "$WGS_API_PORT" "$WGS_WEB_PORT" <<'PY'
import sys
import time
import httpx
for port, path in [(sys.argv[1], '/health'), (sys.argv[2], '/chat'), (sys.argv[2], '/backend/api/agents')]:
    for attempt in range(30):
        try:
            r = httpx.get(f'http://127.0.0.1:{port}{path}', timeout=3)
            r.raise_for_status()
            if path.endswith('/agents'):
                assert [a['id'] for a in r.json()] == ['fmt-researcher']
            print(f'OK {port}{path}: {r.status_code}')
            break
        except (httpx.HTTPError, AssertionError):
            time.sleep(.5)
    else:
        raise SystemExit(f'Activation health check failed: {port}{path}')
PY
trap - ERR
echo "Agent runtime activated. Configuration backup: $BACKUP"
