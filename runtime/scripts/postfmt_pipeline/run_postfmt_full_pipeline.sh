#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd -- "$SCRIPT_ROOT/../../.." && pwd)"
source "$APP_ROOT/runtime/scripts/runtime_paths.sh"
PROJECT_ROOT="${PROJECT_ROOT:-$APP_ROOT}"
RAW_ROOT="$FMT_ROOT/postfmt_raw"
SOURCE_MANIFEST="$FMT_ROOT/postfmt_inventory/postfmt_core_manifest.tsv"
PROCESSING_ROOT="$FMT_ROOT/postfmt_processing_manifest"
PROCESSED_ROOT="$WGS_BIOINFORMATICS_OUTPUT_ROOT"
THREADS_PER_SAMPLE="${THREADS_PER_SAMPLE:-8}"
PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"
LIMIT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --limit) LIMIT="$2"; shift 2 ;;
        --threads-per-sample) THREADS_PER_SAMPLE="$2"; shift 2 ;;
        --parallel-samples) PARALLEL_SAMPLES="$2"; shift 2 ;;
        -h|--help)
            printf 'Usage: %s [--limit N] [--threads-per-sample N] [--parallel-samples N]\n' "$(basename "$0")"
            exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done

[[ -s "$FMT_ROOT/runtime/.fmt_resources_complete" ]] || {
    printf 'FMT resources are not fully deployed yet.\n' >&2
    exit 3
}
[[ -d "$RAW_ROOT" ]] || { printf 'Missing raw data: %s\n' "$RAW_ROOT" >&2; exit 2; }
[[ -s "$SOURCE_MANIFEST" ]] || { printf 'Missing manifest: %s\n' "$SOURCE_MANIFEST" >&2; exit 2; }

mkdir -p "$PROCESSING_ROOT" "$PROCESSED_ROOT/status" "$PROCESSED_ROOT/matrices"

python3 "$SCRIPT_ROOT/build_postfmt_processing_manifest.py" \
    --manifest "$SOURCE_MANIFEST" \
    --raw-root "$RAW_ROOT" \
    --output-dir "$PROCESSING_ROOT"

runner=(
    python3 "$SCRIPT_ROOT/run_postfmt_samples.py"
    --processing-manifest "$PROCESSING_ROOT/processing_manifest.tsv"
    --worker "$SCRIPT_ROOT/process_postfmt_sample.sh"
    --threads-per-sample "$THREADS_PER_SAMPLE"
    --parallel-samples "$PARALLEL_SAMPLES"
    --status-file "$PROCESSED_ROOT/status/runner_status.tsv"
)
if [[ -n "$LIMIT" ]]; then
    runner+=(--limit "$LIMIT")
fi
"${runner[@]}"

python3 "$SCRIPT_ROOT/aggregate_postfmt_profiles.py" \
    --processed-root "$PROCESSED_ROOT" \
    --output-dir "$PROCESSED_ROOT/matrices"

cp "$PROCESSING_ROOT/sample_metadata.tsv" "$PROCESSED_ROOT/matrices/sample_metadata.tsv"
printf 'Pipeline completed at %s\n' "$(date -Is)"
