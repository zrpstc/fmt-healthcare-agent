#!/usr/bin/env bash
# Backfill this project's specialist annotation and activate its report adapter.
set -euo pipefail
if (( EUID != 0 )); then
  echo 'SERVICE_OWNER_REQUIRED'
  exit 2
fi
source "$(dirname "$0")/common.sh"
sample_id="test_complete_data"
if (( $# > 0 )); then sample_id="$1"; fi
[[ "$sample_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$ ]] || { echo 'INVALID_SAMPLE_ID'; exit 2; }
"$WGS_ENV_ROOT/bin/python" -B "$ROOT/scripts/refresh_specialized_metabolism.py" \
  --sample-id "$sample_id" --output-root "$DATA_ROOT/bioinformatics" \
  --results-dir "$DATA_ROOT/results" --mapping-dir "$ROOT/fmt-databases/humann3/utility_mapping"
bash "$ROOT/deploy/restart-report-api.sh"
echo 'SPECIALIZED_WORKFLOW_ACTIVATED'
