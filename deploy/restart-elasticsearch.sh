#!/usr/bin/env bash
# Restart only the Elasticsearch this project uses; application processes are left alone.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/deploy/lib/restart_elasticsearch.py"
[[ -x "$PYTHON" ]] || { echo '{"ok":false,"error":"PROJECT_PYTHON_MISSING"}' >&2; exit 1; }
if "$PYTHON" "$SCRIPT" "$@"; then
  exit 0
else
  result=$?
fi
# 77: Docker needs administrator rights; authenticate interactively like the other entry points.
if [[ "$result" == 77 && "$EUID" != 0 && -t 0 ]] && command -v sudo >/dev/null 2>&1; then
  exec sudo -- "$PYTHON" "$SCRIPT" "$@"
fi
exit "$result"
