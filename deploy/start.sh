#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${WGS_APP_ROOT:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"

cd "$ROOT"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DATA_ROOT="${WGS_WORKSPACE:-$ROOT/var}"
LAYOUT_FMT_ROOT="$(cd -- "$ROOT/../.." 2>/dev/null && pwd || true)"
if [[ -n "${WGS_ENV_ROOT:-}" ]]; then
  ENV_ROOT="$WGS_ENV_ROOT"
elif [[ -x "${FMT_ROOT:-${WGS_FMT_RESOURCE_ROOT:-$ROOT/var}}/runtime/envs/wgs-fmt-agent-v2/bin/python" ]]; then
  ENV_ROOT="${FMT_ROOT:-${WGS_FMT_RESOURCE_ROOT:-$ROOT/var}}/runtime/envs/wgs-fmt-agent-v2"
elif [[ -n "$LAYOUT_FMT_ROOT" && -x "$LAYOUT_FMT_ROOT/runtime/envs/wgs-fmt-agent-v2/bin/python" ]]; then
  # Standard deployment layout: <fmt-root>/apps/WGS-FMT-Agent-v2.
  ENV_ROOT="$LAYOUT_FMT_ROOT/runtime/envs/wgs-fmt-agent-v2"
else
  ENV_ROOT="$ROOT/.venv"
fi
WEB_HOST="${WGS_WEB_HOST:-0.0.0.0}"
WEB_PORT="${WGS_WEB_PORT:-8502}"
API_HOST="${WGS_API_HOST:-0.0.0.0}"
API_PORT="${WGS_API_PORT:-8503}"

[[ -x "$ENV_ROOT/bin/python" ]] || {
  printf 'Application Python environment missing: %s\n' "$ENV_ROOT" >&2
  exit 2
}
[[ -x "$ROOT/apps/workspace-web/node_modules/.bin/next" ]] || {
  printf 'Frontend build dependencies missing; run npm ci and npm run build.\n' >&2
  exit 2
}

mkdir -p "$DATA_ROOT/logs" "$DATA_ROOT/run" "$DATA_ROOT/results" \
  "$DATA_ROOT/traces" "$DATA_ROOT/knowledge-index"

start_service() {
  local name="$1"
  local pid_file="$DATA_ROOT/run/$name.pid"
  local log_file="$DATA_ROOT/logs/$name.log"
  shift
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$name already running: PID $(cat "$pid_file")"
    return
  fi
  nohup "$@" >"$log_file" 2>&1 &
  echo "$!" >"$pid_file"
  echo "$name started: PID $!"
}

start_service workspace-api "$ENV_ROOT/bin/python" -m uvicorn app.main:app \
  --app-dir "$ROOT/apps/workspace-api" --host "$API_HOST" --port "$API_PORT"
start_service workspace-web "$ROOT/apps/workspace-web/node_modules/.bin/next" \
  start "$ROOT/apps/workspace-web" -p "$WEB_PORT" -H "$WEB_HOST"

if [[ "${WGS_ENABLE_REVERSE_TUNNELS:-false}" == true ]]; then
  bash "$ROOT/deploy/restore-reverse-tunnels.sh"
else
  echo "reverse tunnels disabled (set WGS_ENABLE_REVERSE_TUNNELS=true to enable)"
fi

if [[ -n "${DEEPSEEK_API_KEY:-}" || -n "${ANTHROPIC_API_KEY:-}" ]]; then
  start_service agent-daemon "$ENV_ROOT/bin/wgs-agent" daemon --host 127.0.0.1 --port 7438
else
  echo "agent-daemon skipped: configure DEEPSEEK_API_KEY or ANTHROPIC_API_KEY"
fi
