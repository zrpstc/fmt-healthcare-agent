#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PYTHON="$ROOT/.venv/bin/python"
case "${1:-}" in
  start|stop|restart|status) ;;
  *) echo '{"ok":false,"error":"UNKNOWN_DEPLOY_ACTION"}' >&2; exit 2 ;;
esac
[[ -x "$PYTHON" ]] || { echo '{"ok":false,"error":"PROJECT_PYTHON_MISSING"}' >&2; exit 1; }
if "$PYTHON" "$ROOT/deploy/lib/runtime.py" "$@"; then
  exit 0
else
  result=$?
fi
if [[ "$result" == 77 && "$EUID" != 0 && -t 0 ]] && command -v sudo >/dev/null 2>&1; then
  exec sudo -- "$PYTHON" "$ROOT/deploy/lib/runtime.py" "$@"
fi
exit "$result"
