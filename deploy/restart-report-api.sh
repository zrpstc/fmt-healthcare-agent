#!/usr/bin/env bash
# Activate backend-only report changes without stopping the Web or workers.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

pid_file="$DATA_ROOT/run/workspace-api.pid"
log_file="$DATA_ROOT/logs/workspace-api.log"
if [[ ! -r "$pid_file" ]]; then
  echo "Cannot read API PID file; run this script as the API owner (currently root)." >&2
  exit 1
fi
pid="$(cat "$pid_file")"
if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid API PID file; no process was stopped." >&2
  exit 1
fi
if [[ -d "/proc/$pid" ]]; then
  command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  if [[ "$command_line" != *"$ROOT/"* || "$command_line" != *"uvicorn app.main:app"* || "$command_line" != *"--port $WGS_API_PORT "* ]]; then
    echo "PID does not match this project's API and port; no process was stopped." >&2
    exit 1
  fi
  kill -TERM "$pid"
  for attempt in {1..50}; do
    [[ ! -d "/proc/$pid" ]] && break
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    [[ "$state" == Z ]] && break
    sleep 0.2
  done
  if [[ -d "/proc/$pid" && "${state:-}" != Z ]]; then
    echo "API has not stopped; no replacement was started." >&2
    exit 1
  fi
fi
umask 077
nohup "$WGS_ENV_ROOT/bin/python" -m uvicorn app.main:app \
  --app-dir "$ROOT/apps/workspace-api" --host 127.0.0.1 --port "$WGS_API_PORT" \
  >>"$log_file" 2>&1 < /dev/null &
new_pid=$!
printf '%s\n' "$new_pid" > "$pid_file"
for attempt in {1..40}; do
  if ! kill -0 "$new_pid" 2>/dev/null; then
    echo "Replacement API exited; inspect $log_file." >&2
    exit 1
  fi
  if curl -fsS --max-time 2 "http://127.0.0.1:$WGS_API_PORT/health" >/dev/null; then
    echo "API restarted and healthy: PID $new_pid, port $WGS_API_PORT."
    exit 0
  fi
  sleep 0.5
done
echo "API health check timed out; inspect $log_file." >&2
exit 1
