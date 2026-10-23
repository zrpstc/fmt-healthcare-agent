#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
exec "$WGS_ENV_ROOT/bin/python" "$ROOT/scripts/diagnose_elasticsearch.py" "$@"
