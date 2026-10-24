#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
WEB_BUILD_DIR="${WGS_WEB_DIST_DIR:-.next}"

if [[ ! -x "$WGS_ENV_ROOT/bin/python" || ! -x "$ROOT/apps/workspace-web/node_modules/.bin/next" || ! -f "$ROOT/apps/workspace-web/$WEB_BUILD_DIR/BUILD_ID" ]]; then
  echo "Install Python/Web dependencies and build the Web app before starting." >&2
  exit 2
fi
"$WGS_ENV_ROOT/bin/python" - "$ROOT/apps/workspace-web/$WEB_BUILD_DIR/routes-manifest.json" "$WGS_API_PORT" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    rewrites = json.load(handle)["rewrites"]
routes = rewrites if isinstance(rewrites, list) else [route for group in rewrites.values() for route in group]
expected = f"http://127.0.0.1:{int(sys.argv[2])}/:path*"
if not any(route.get("source") == "/backend/:path*" and route.get("destination") == expected for route in routes):
    raise SystemExit("API port differs from the Web build; rebuild the Web app before starting.")
PY
umask 077
"$WGS_ENV_ROOT/bin/python" "$ROOT/scripts/init_data.py"

if [[ "$WGS_ELASTICSEARCH_MANAGED" == true ]]; then
  manage_elasticsearch start
  export WGS_ELASTICSEARCH_USERNAME=wgs-platform
  export WGS_ELASTICSEARCH_PASSWORD_FILE="$DATA_ROOT/elasticsearch/client-password"
  export WGS_ELASTICSEARCH_API_KEY=""
  # Create the empty keyword/vector index before serving requests.
  "$WGS_ENV_ROOT/bin/python" -c 'from wgs_fmt_platform.infrastructure.search import HybridKnowledgeSearch; HybridKnowledgeSearch().ensure_index()'
else
  echo "elasticsearch external: automatic startup disabled"
fi

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

start_service workspace-api "$WGS_ENV_ROOT/bin/python" -m uvicorn app.main:app \
  --app-dir "$ROOT/apps/workspace-api" --host 127.0.0.1 --port "$WGS_API_PORT"
start_service workspace-web "$ROOT/apps/workspace-web/node_modules/.bin/next" \
  start "$ROOT/apps/workspace-web" -p "$WGS_WEB_PORT" -H "$WGS_WEB_HOST"

if [[ -n "${DEEPSEEK_API_KEY:-}" || -n "${ANTHROPIC_API_KEY:-}" ]]; then
  start_service agent-daemon "$WGS_ENV_ROOT/bin/wgs-agent" daemon --host 127.0.0.1 --port "$WGS_PORT"
else
  echo "agent-daemon skipped: configure DEEPSEEK_API_KEY or ANTHROPIC_API_KEY"
fi

echo "Workspace URL: http://<server-ip>:$WGS_WEB_PORT/"
