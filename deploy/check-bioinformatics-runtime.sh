#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$APP_ROOT/runtime/scripts/runtime_paths.sh"
MODEL_ROOT="$WGS_FMT_TRIPLET_MODEL_DIR"
BASELINE_SPECIES="$WGS_FMT_BASELINE_SPECIES"
MATCH_FILE="$WGS_FMT_MATCH_FILE"
ALLOW_MISSING_DATABASES=false
if [[ "${1:-}" == "--allow-missing-databases" ]]; then
    ALLOW_MISSING_DATABASES=true
fi

missing=0
check_path() {
    local path="$1"
    local type="${2:-file}"
    if [[ "$type" == executable && ! -x "$path" ]]; then
        printf 'MISSING executable %s\n' "$path" >&2
        missing=$((missing + 1))
    elif [[ "$type" == directory && ! -d "$path" ]]; then
        printf 'MISSING directory  %s\n' "$path" >&2
        missing=$((missing + 1))
    elif [[ "$type" == file && ! -s "$path" ]]; then
        printf 'MISSING file       %s\n' "$path" >&2
        missing=$((missing + 1))
    else
        printf 'OK      %s\n' "$path"
    fi
}

check_path "$APP_ROOT/runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh" executable
check_path "$ENV_ROOT/fmt-tax/bin/fastp" executable
check_path "$ENV_ROOT/fmt-tax/bin/kneaddata" executable
check_path "$ENV_ROOT/fmt-tax/bin/metaphlan" executable
check_path "$ENV_ROOT/fmt-tax/bin/pigz" executable
check_path "$ENV_ROOT/fmt-func/bin/humann" executable
check_path "$ENV_ROOT/fmt-func/bin/humann_renorm_table" executable

if ! wgs_run_tool "$ENV_ROOT/fmt-func" "$ENV_ROOT/fmt-func/bin/glpsol" --version >/dev/null 2>&1; then
    printf "MISSING GLPK_RUNTIME: configured fmt-func shared libraries could not be loaded\n" >&2
    missing=$((missing + 1))
fi

if [[ "$ALLOW_MISSING_DATABASES" != true ]]; then
    check_path "$DB_ROOT/kneaddata/hg_39/hg_39.1.bt2"
    check_path "$DB_ROOT/metaphlan4/mpa_vJan25_CHOCOPhlAnSGB_202503.pkl"
    check_path "$DB_ROOT/metaphlan4_vJun23/mpa_vJun23_CHOCOPhlAnSGB_202307.pkl"
    check_path "$DB_ROOT/humann3/chocophlan" directory
    check_path "$DB_ROOT/humann3/uniref/uniref90_201901b_full.dmnd"
    check_path "$DB_ROOT/humann3/utility_mapping/map_ko_uniref90.txt.gz"
    check_path "$MODEL_ROOT/feature_schema.json"
    check_path "$MODEL_ROOT/fmt_triplet_contrastive_model.npz"
    check_path "$BASELINE_SPECIES"
    check_path "$MATCH_FILE"
fi

if (( missing > 0 )); then
    printf '\nRuntime check failed: %d required path(s) missing.\n' "$missing" >&2
    exit 1
fi
printf '\nRuntime check passed for FMT_ROOT=%s\n' "$FMT_ROOT"
