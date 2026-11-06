#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo '{"ok":false,"error":"PROJECT_PYTHON_MISSING"}' >&2; exit 1; }
if "$PYTHON" "$ROOT/deploy/runtime.py" "$@"; then
  exit 0
else
  result=$?
fi
# An interactive operator authenticates directly with sudo; credentials never enter application arguments.
if [[ "$result" == 77 && "$EUID" != 0 && -t 0 ]] && command -v sudo >/dev/null 2>&1; then
  exec sudo -- "$PYTHON" "$ROOT/deploy/runtime.py" "$@"
fi
exit "$result"
