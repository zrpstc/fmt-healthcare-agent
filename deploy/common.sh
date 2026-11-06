#!/usr/bin/env bash
# Shared path/environment resolution. Sourcing this file does not start services.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export WGS_APP_ROOT="$ROOT"
export WGS_ENV_ROOT="${WGS_ENV_ROOT:-$ROOT/.venv}"
export WGS_WORKSPACE="${WGS_WORKSPACE:-$ROOT/var}"
if [[ "$WGS_WORKSPACE" != /* ]]; then
  WGS_WORKSPACE="$ROOT/$WGS_WORKSPACE"
fi
if [[ "$WGS_ENV_ROOT" != /* ]]; then
  WGS_ENV_ROOT="$ROOT/$WGS_ENV_ROOT"
fi
DATA_ROOT="$WGS_WORKSPACE"
export PATH="$WGS_ENV_ROOT/bin:$PATH"
export WGS_WEB_HOST="${WGS_WEB_HOST:-0.0.0.0}"
export WGS_WEB_PORT="${WGS_WEB_PORT:-18502}"
export WGS_API_PORT="${WGS_API_PORT:-18503}"
export WGS_PORT="${WGS_PORT:-7438}"
export WGS_ELASTICSEARCH_URL="${WGS_ELASTICSEARCH_URL:-http://127.0.0.1:9200}"
export WGS_ELASTICSEARCH_MANAGED="${WGS_ELASTICSEARCH_MANAGED:-true}"
case "${WGS_ELASTICSEARCH_MANAGED,,}" in
  true|1) WGS_ELASTICSEARCH_MANAGED=true ;;
  false|0) WGS_ELASTICSEARCH_MANAGED=false ;;
  *) echo "WGS_ELASTICSEARCH_MANAGED must be true or false" >&2; exit 2 ;;
esac

manage_elasticsearch() {
  local interpreter="$WGS_ENV_ROOT/bin/python"
  if [[ ! -x "$interpreter" ]]; then
    interpreter=python3
  fi
  "$interpreter" "$ROOT/scripts/manage_elasticsearch.py" "$@"
}

for port in "$WGS_WEB_PORT" "$WGS_API_PORT" "$WGS_PORT"; do
  if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
    echo "Invalid service port: $port" >&2
    exit 2
  fi
done
if (( 10#$WGS_WEB_PORT == 10#$WGS_API_PORT || 10#$WGS_WEB_PORT == 10#$WGS_PORT || 10#$WGS_API_PORT == 10#$WGS_PORT )); then
  echo "Web, API and daemon ports must be distinct" >&2
  exit 2
fi
