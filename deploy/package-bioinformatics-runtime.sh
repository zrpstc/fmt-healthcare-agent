#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$APP_ROOT/runtime/scripts/runtime_paths.sh"
BUNDLE_DIR="${1:-}"

[[ -n "$BUNDLE_DIR" ]] || {
    printf 'Usage: FMT_ROOT=/source/root %s OUTPUT_DIRECTORY\n' "$(basename "$0")" >&2
    exit 2
}
command -v zstd >/dev/null 2>&1 || { printf 'zstd is required.\n' >&2; exit 2; }
command -v sha256sum >/dev/null 2>&1 || { printf 'sha256sum is required.\n' >&2; exit 2; }
command -v conda-pack >/dev/null 2>&1 || {
    printf 'conda-pack is required for relocatable environment archives.\n' >&2
    printf 'Install it in the base environment: conda install -c conda-forge conda-pack\n' >&2
    exit 2
}
mkdir -p "$BUNDLE_DIR"

environments=(
    fmt-tax
    fmt-func
)
databases=(
    databases/kneaddata
    databases/metaphlan4
    databases/metaphlan4_vJun23
    databases/humann3
)

FMT_ROOT="$FMT_ROOT" "$SCRIPT_DIR/check-bioinformatics-runtime.sh"
checksum_file="$BUNDLE_DIR/SHA256SUMS"
: > "$checksum_file"
for environment in "${environments[@]}"; do
    archive_name="environment_${environment}.tar.gz"
    archive="$BUNDLE_DIR/$archive_name"
    printf 'PACK relocatable environment %s -> %s\n' "$ENV_ROOT/$environment" "$archive"
    conda-pack --prefix "$ENV_ROOT/$environment" --output "$archive" --force
    (
        cd -- "$BUNDLE_DIR"
        sha256sum "$archive_name"
    ) >> "$checksum_file"
done
for relative in "${databases[@]}"; do
    archive_name="${relative//\//_}.tar.zst"
    archive="$BUNDLE_DIR/$archive_name"
    printf 'PACK %s -> %s\n' "$DB_ROOT/${relative#databases/}" "$archive"
    tar -C "$DB_ROOT" --transform='flags=rh;s,^,databases/,' -cf - "${relative#databases/}" | zstd -T0 -10 -f -o "$archive"
    (
        cd -- "$BUNDLE_DIR"
        sha256sum "$archive_name"
    ) >> "$checksum_file"
done

model_source="$WGS_FMT_TRIPLET_MODEL_DIR"
[[ -s "$model_source/feature_schema.json" && -s "$model_source/fmt_triplet_contrastive_model.npz" ]] || {
    printf 'FMT triplet model is missing: %s\n' "$model_source" >&2
    exit 2
}
model_archive_name="model_fmt-triplet-v1.tar.zst"
printf 'PACK model %s -> %s/%s\n' "$model_source" "$BUNDLE_DIR" "$model_archive_name"
tar -C "$model_source" -cf - . | zstd -T0 -10 -f -o "$BUNDLE_DIR/$model_archive_name"
(
    cd -- "$BUNDLE_DIR"
    sha256sum "$model_archive_name"
) >> "$checksum_file"

matching_source="$WGS_FMT_MATCHING_DIR"
baseline_source="$WGS_FMT_BASELINE_SPECIES"
match_source="$WGS_FMT_MATCH_FILE"
[[ -s "$baseline_source" && -s "$match_source" ]] || {
    printf 'FMT matching baseline or match metadata is missing.\n' >&2
    exit 2
}
matching_archive_name="data_fmt-matching.tar.zst"
printf 'PACK restricted matching data -> %s/%s\n' "$BUNDLE_DIR" "$matching_archive_name"
tar -cf - -C "$(dirname "$baseline_source")" "$(basename "$baseline_source")" \
    -C "$(dirname "$match_source")" "$(basename "$match_source")" \
    | zstd -T0 -10 -f -o "$BUNDLE_DIR/$matching_archive_name"
(
    cd -- "$BUNDLE_DIR"
    sha256sum "$matching_archive_name"
) >> "$checksum_file"
cp "$APP_ROOT/runtime/resources/manifest.json" "$BUNDLE_DIR/manifest.json"
printf 'Bundle complete: %s\n' "$BUNDLE_DIR"
