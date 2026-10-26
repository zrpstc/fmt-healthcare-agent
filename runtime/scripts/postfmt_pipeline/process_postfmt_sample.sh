#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    printf 'Usage: %s --group-json FILE [--threads N]\n' "$(basename "$0")"
}

GROUP_JSON=""
THREADS="${THREADS:-8}"
METAPHLAN_THREADS="${METAPHLAN_THREADS:-4}"
HUMANN_MEMORY_USE="${HUMANN_MEMORY_USE:-minimum}"
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd -- "$SCRIPT_ROOT/../../.." && pwd)"
if [[ -z "${FMT_ROOT:-}" ]]; then
    if [[ -n "${WGS_FMT_RESOURCE_ROOT:-}" ]]; then
        FMT_ROOT="$WGS_FMT_RESOURCE_ROOT"
    elif [[ -n "${WGS_WORKSPACE:-}" ]]; then
        FMT_ROOT="$(dirname -- "$WGS_WORKSPACE")"
    else
        FMT_ROOT="$APP_ROOT/var"
    fi
fi
OUTPUT_ROOT="${OUTPUT_ROOT:-$FMT_ROOT/postfmt_processed}"
DB_ROOT="${DB_ROOT:-$FMT_ROOT/databases}"
ENV_ROOT="${ENV_ROOT:-$FMT_ROOT/runtime/envs}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --group-json) GROUP_JSON="$2"; shift 2 ;;
        --threads) THREADS="$2"; shift 2 ;;
        --output-root) OUTPUT_ROOT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage; exit 2 ;;
    esac
done

[[ -f "$GROUP_JSON" ]] || { printf 'Missing group JSON: %s\n' "$GROUP_JSON" >&2; exit 2; }

PYTHON="${PYTHON:-python3}"
SAMPLE_ID="$($PYTHON -c 'import json,sys; print(json.load(open(sys.argv[1]))["sample_id"])' "$GROUP_JSON")"
WORK_DIR="$OUTPUT_ROOT/work/$SAMPLE_ID"
FASTP_DIR="$WORK_DIR/fastp"
KNEAD_DIR="$WORK_DIR/knead"
MERGED_FASTQ="$WORK_DIR/${SAMPLE_ID}.dehosted.fastq"
METAPHLAN_OUT="$OUTPUT_ROOT/profiles/metaphlan/${SAMPLE_ID}_profile.tsv"
HUMANN_DIR="$OUTPUT_ROOT/profiles/humann"
HUMANN_SAMPLE_DIR="$WORK_DIR/humann"
QC_DIR="$OUTPUT_ROOT/qc/$SAMPLE_ID"
CLEAN_DIR="$OUTPUT_ROOT/clean_merged"
LOG_DIR="$OUTPUT_ROOT/logs"
DONE_DIR="$OUTPUT_ROOT/status/done"
FAILED_DIR="$OUTPUT_ROOT/status/failed"
LOCK_DIR="$OUTPUT_ROOT/status/locks/${SAMPLE_ID}.lock"
LOG_FILE="$LOG_DIR/${SAMPLE_ID}.log"

TAX_ENV="$ENV_ROOT/fmt-tax"
FUNC_ENV="$ENV_ROOT/fmt-func"
export PATH="$TAX_ENV/bin:$FUNC_ENV/bin:$PATH"
FASTP="$TAX_ENV/bin/fastp"
KNEADDATA="$TAX_ENV/bin/kneaddata"
METAPHLAN="$TAX_ENV/bin/metaphlan"
PIGZ="$TAX_ENV/bin/pigz"
HUMANN="$FUNC_ENV/bin/humann"
HUMANN_RENORM="$FUNC_ENV/bin/humann_renorm_table"

KNEADDATA_DB="$DB_ROOT/kneaddata/hg_39"
METAPHLAN_DB="$DB_ROOT/metaphlan4"
METAPHLAN_INDEX="${METAPHLAN_INDEX:-mpa_vJan25_CHOCOPhlAnSGB_202503}"
HUMANN_METAPHLAN_DB="${HUMANN_METAPHLAN_DB:-$DB_ROOT/metaphlan4_vJun23}"
HUMANN_METAPHLAN_INDEX="${HUMANN_METAPHLAN_INDEX:-mpa_vJun23_CHOCOPhlAnSGB_202307}"
HUMANN_NUC_DB="$DB_ROOT/humann3/chocophlan"
HUMANN_PROT_DB="$DB_ROOT/humann3/uniref"

prepare_healthy_comparison() {
    [[ "${WGS_HEALTHY_REFERENCE_PROVIDER:-}" == "mho" ]] || return 0
    local app_python="${WGS_MHO_PYTHON:-$APP_ROOT/.venv/bin/python}"
    if [[ ! -x "$app_python" ]]; then
        printf 'HEALTHY_REFERENCE unavailable: application Python missing\n' >&2
        return 0
    fi
    if ! ENV_ROOT="$ENV_ROOT" DB_ROOT="$DB_ROOT" \
        PYTHONPATH="$APP_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
        "$app_python" -m wgs_agent.pipeline.mho_workflow ensure \
        --sample-id "$SAMPLE_ID" --output-root "$OUTPUT_ROOT" \
        --group-json "$GROUP_JSON" --threads "${WGS_MHO_THREADS:-$METAPHLAN_THREADS}"; then
        printf 'HEALTHY_REFERENCE failed; see independent workflow state\n' >&2
    fi
}

mkdir -p "$FASTP_DIR" "$KNEAD_DIR" "$HUMANN_SAMPLE_DIR" "$QC_DIR" \
    "$CLEAN_DIR" "$LOG_DIR" "$DONE_DIR" "$FAILED_DIR" "$(dirname "$LOCK_DIR")" \
    "$(dirname "$METAPHLAN_OUT")" "$HUMANN_DIR"

if [[ -s "$DONE_DIR/${SAMPLE_ID}.done" ]]; then
    if [[ -s "$METAPHLAN_OUT" \
        && -s "$HUMANN_DIR/${SAMPLE_ID}_pathabundance_relab.tsv" \
        && -s "$HUMANN_DIR/${SAMPLE_ID}_genefamilies_relab.tsv" \
        && -s "$CLEAN_DIR/${SAMPLE_ID}.dehosted.fastq.gz" ]]; then
        prepare_healthy_comparison
        printf 'SKIP complete: %s\n' "$SAMPLE_ID"
        exit 0
    fi
    rm -f "$DONE_DIR/${SAMPLE_ID}.done"
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    printf 'SKIP locked: %s\n' "$SAMPLE_ID" >&2
    exit 3
fi

on_exit() {
    local code=$?
    trap - EXIT
    rmdir "$LOCK_DIR" 2>/dev/null || true
    if (( code != 0 )); then
        printf '%s\texit=%s\tlog=%s\n' "$(date -Is)" "$code" "$LOG_FILE" \
            > "$FAILED_DIR/${SAMPLE_ID}.failed"
    fi
    exit "$code"
}
trap on_exit EXIT

exec > >(tee -a "$LOG_FILE") 2>&1
rm -f "$FAILED_DIR/${SAMPLE_ID}.failed"

log() {
    printf '[%s] [%s] %s\n' "$(date '+%F %T')" "$SAMPLE_ID" "$*"
}

require_file() {
    [[ -s "$1" ]] || { log "ERROR missing/empty file: $1"; return 1; }
}

for tool in "$FASTP" "$KNEADDATA" "$METAPHLAN" "$HUMANN" "$HUMANN_RENORM"; do
    [[ -x "$tool" ]] || { log "ERROR missing executable: $tool"; exit 2; }
done
for path in \
    "$KNEADDATA_DB/hg_39.1.bt2" \
    "$METAPHLAN_DB/$METAPHLAN_INDEX.pkl" \
    "$HUMANN_PROT_DB/uniref90_201901b_full.dmnd"; do
    [[ -e "$path" ]] || { log "ERROR missing database component: $path"; exit 2; }
done

mapfile -t RUN_ROWS < <(
    "$PYTHON" - "$GROUP_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    group = json.load(handle)
for run in group["runs"]:
    if run["layout"] == "paired":
        print("\t".join([run["run_accession"], "paired", run["r1"], run["r2"]]))
    else:
        print("\t".join([run["run_accession"], "single", run["single"], ""]))
PY
)

log "START biological sample with ${#RUN_ROWS[@]} run(s), threads=$THREADS"
clean_reads=()

for row in "${RUN_ROWS[@]}"; do
    IFS=$'\t' read -r run layout input1 input2 <<< "$row"
    require_file "$input1"
    run_knead="$KNEAD_DIR/$run"
    mkdir -p "$run_knead"

    if [[ "$layout" == "paired" ]]; then
        require_file "$input2"
        clean1="$FASTP_DIR/${run}_1.clean.fastq.gz"
        clean2="$FASTP_DIR/${run}_2.clean.fastq.gz"
        knead1="$run_knead/${run}_paired_1.fastq"
        knead2="$run_knead/${run}_paired_2.fastq"

        if [[ ! -s "$clean1" || ! -s "$clean2" ]]; then
            log "FASTP paired $run"
            "$FASTP" \
                -i "$input1" -I "$input2" -o "$clean1" -O "$clean2" \
                --detect_adapter_for_pe --thread "$THREADS" \
                --html "$QC_DIR/${run}_fastp.html" \
                --json "$QC_DIR/${run}_fastp.json" \
                --compression 6 --cut_front --cut_tail --cut_window_size 4 \
                --cut_mean_quality 20 --length_required 50 --average_qual 20
        fi
        if [[ ! -s "$knead1" || ! -s "$knead2" ]]; then
            log "KNEADDATA paired $run"
            "$KNEADDATA" \
                --input1 "$clean1" --input2 "$clean2" --output "$run_knead" \
                --threads "$THREADS" --output-prefix "$run" \
                --reference-db "$KNEADDATA_DB" --bypass-trf \
                --remove-intermediate-output
        fi
        require_file "$knead1"
        require_file "$knead2"
        clean_reads+=("$knead1" "$knead2")
    else
        clean1="$FASTP_DIR/${run}.clean.fastq.gz"
        knead_single="$run_knead/${run}.fastq"
        if [[ ! -s "$clean1" ]]; then
            log "FASTP single $run"
            "$FASTP" \
                -i "$input1" -o "$clean1" --thread "$THREADS" \
                --html "$QC_DIR/${run}_fastp.html" \
                --json "$QC_DIR/${run}_fastp.json" \
                --compression 6 --cut_front --cut_tail --cut_window_size 4 \
                --cut_mean_quality 20 --length_required 50 --average_qual 20
        fi
        if [[ ! -s "$knead_single" ]]; then
            log "KNEADDATA single $run"
            "$KNEADDATA" \
                --unpaired "$clean1" --output "$run_knead" \
                --threads "$THREADS" --output-prefix "$run" \
                --reference-db "$KNEADDATA_DB" --bypass-trf \
                --remove-intermediate-output
        fi
        if [[ ! -s "$knead_single" ]]; then
            mapfile -t candidates < <(
                find "$run_knead" -maxdepth 1 -type f -name '*.fastq' \
                    ! -name '*contam*' ! -name '*unmatched*' ! -name '*trimmed*' \
                    -printf '%s\t%p\n' | sort -nr | cut -f2-
            )
            [[ ${#candidates[@]} -gt 0 ]] || { log "ERROR no single-end KneadData output: $run"; exit 1; }
            knead_single="${candidates[0]}"
        fi
        require_file "$knead_single"
        clean_reads+=("$knead_single")
    fi
done

log "MERGE ${#clean_reads[@]} dehosted read files"
: > "$MERGED_FASTQ"
for clean in "${clean_reads[@]}"; do
    cat "$clean" >> "$MERGED_FASTQ"
done
require_file "$MERGED_FASTQ"

if [[ ! -s "$METAPHLAN_OUT" ]]; then
    log "METAPHLAN $METAPHLAN_INDEX"
    jan25_mapout="$WORK_DIR/${SAMPLE_ID}.jan25.mapout.bz2"
    rm -f "$jan25_mapout"
    "$METAPHLAN" "$MERGED_FASTQ" \
        --input_type fastq -o "$METAPHLAN_OUT" \
        --mapout "$jan25_mapout" \
        --db_dir "$METAPHLAN_DB" -x "$METAPHLAN_INDEX" \
        --nproc "$METAPHLAN_THREADS"
    rm -f "$jan25_mapout"
fi
require_file "$METAPHLAN_OUT"

# HUMAnN 3.9 officially supports MetaPhlAn vJun23, while the latest Jan25
# profile above is retained as the primary species-abundance result.
HUMANN_TAX_DIR="$OUTPUT_ROOT/profiles/metaphlan_humann_vJun23"
HUMANN_TAX_OUT="$HUMANN_TAX_DIR/${SAMPLE_ID}_profile.tsv"
mkdir -p "$HUMANN_TAX_DIR"
if [[ ! -s "$HUMANN_TAX_OUT" ]]; then
    log "METAPHLAN HUMANN-compatible $HUMANN_METAPHLAN_INDEX"
    humann_mapout="$WORK_DIR/${SAMPLE_ID}.vJun23.mapout.bz2"
    rm -f "$humann_mapout"
    "$METAPHLAN" "$MERGED_FASTQ" \
        --input_type fastq -o "$HUMANN_TAX_OUT" \
        --mapout "$humann_mapout" \
        --db_dir "$HUMANN_METAPHLAN_DB" -x "$HUMANN_METAPHLAN_INDEX" \
        --nproc "$METAPHLAN_THREADS"
    rm -f "$humann_mapout"
fi
require_file "$HUMANN_TAX_OUT"

pathabundance="$HUMANN_DIR/${SAMPLE_ID}_pathabundance.tsv"
genefamilies="$HUMANN_DIR/${SAMPLE_ID}_genefamilies.tsv"
if [[ ! -s "$pathabundance" || ! -s "$genefamilies" ]]; then
    log "HUMANN functional profiling"
    # HUMAnN 3.9 parses the last nonempty line of `metaphlan --version`.
    # MetaPhlAn 4.2 appends database information; normalize only that probe.
    WGS_HUMANN_METAPHLAN_BIN="$METAPHLAN" \
    PATH="$SCRIPT_ROOT/humann_compat:$FUNC_ENV/bin:$PATH" "$HUMANN" \
        --input "$MERGED_FASTQ" --output "$HUMANN_SAMPLE_DIR" \
        --output-basename "$SAMPLE_ID" --threads "$THREADS" \
        --taxonomic-profile "$HUMANN_TAX_OUT" \
        --nucleotide-database "$HUMANN_NUC_DB" \
        --protein-database "$HUMANN_PROT_DB" \
        --search-mode uniref90 --translated-alignment diamond \
        --memory-use "$HUMANN_MEMORY_USE" --remove-temp-output
    for output in "$HUMANN_SAMPLE_DIR/${SAMPLE_ID}"_*.tsv; do
        [[ -e "$output" ]] || continue
        mv "$output" "$HUMANN_DIR/"
    done
fi
require_file "$pathabundance"
require_file "$genefamilies"

for input in "$pathabundance" "$genefamilies"; do
    base="${input%.tsv}"
    output="${base}_relab.tsv"
    if [[ ! -s "$output" ]]; then
        log "HUMANN normalize $(basename "$input")"
        PATH="$FUNC_ENV/bin:$PATH" "$HUMANN_RENORM" \
            --input "$input" --output "$output" --units relab
    fi
    require_file "$output"
done

clean_output="$CLEAN_DIR/${SAMPLE_ID}.dehosted.fastq.gz"
if [[ ! -s "$clean_output" ]]; then
    log "COMPRESS merged dehosted reads"
    if [[ -x "$PIGZ" ]]; then
        "$PIGZ" -p "$THREADS" -c "$MERGED_FASTQ" > "$clean_output.tmp"
    else
        gzip -c "$MERGED_FASTQ" > "$clean_output.tmp"
    fi
    mv "$clean_output.tmp" "$clean_output"
fi
require_file "$clean_output"

# Reuse the completed dehosted input; preserve the main analysis if this
# independent reference branch fails. Reports already consume its profile.
prepare_healthy_comparison

printf '%s\t%s\t%s\n' "$(date -Is)" "$SAMPLE_ID" "$GROUP_JSON" \
    > "$DONE_DIR/${SAMPLE_ID}.done"
log "COMPLETE"
rm -rf "$WORK_DIR" || true
