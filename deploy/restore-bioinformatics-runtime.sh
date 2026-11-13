#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$APP_ROOT/runtime/scripts/runtime_paths.sh"
BUNDLE_DIR="${1:-}"

[[ -d "$BUNDLE_DIR" ]] || {
    printf 'Usage: FMT_ROOT=/target/root %s BUNDLE_DIRECTORY\n' "$(basename "$0")" >&2
    exit 2
}
command -v zstd >/dev/null 2>&1 || { printf 'zstd is required.\n' >&2; exit 2; }
command -v sha256sum >/dev/null 2>&1 || { printf 'sha256sum is required.\n' >&2; exit 2; }
[[ -s "$BUNDLE_DIR/SHA256SUMS" ]] || { printf 'Missing SHA256SUMS.\n' >&2; exit 2; }

(
    cd -- "$BUNDLE_DIR"
    sha256sum --check SHA256SUMS
)
mkdir -p "$FMT_ROOT"
for archive in "$BUNDLE_DIR"/environment_*.tar.gz; do
    [[ -e "$archive" ]] || continue
    environment="$(basename "$archive" .tar.gz)"
    environment="${environment#environment_}"
    target="$ENV_ROOT/$environment"
    [[ ! -e "$target" ]] || {
        printf 'Target environment already exists; move it aside first: %s\n' "$target" >&2
        exit 3
    }
    printf 'INSPECT %s\n' "$archive"
    while IFS= read -r member; do
        if [[ "$member" == /* || "$member" == ../* || "$member" == */../* ]]; then
            printf 'Unsafe archive member rejected: %s\n' "$member" >&2
            exit 3
        fi
    done < <(tar -tzf "$archive")
    mkdir -p "$target"
    printf 'RESTORE environment %s -> %s\n' "$archive" "$target"
    tar -xzf "$archive" -C "$target"
    [[ -x "$target/bin/conda-unpack" ]] || {
        printf 'Invalid conda-pack archive: conda-unpack missing in %s\n' "$target" >&2
        exit 3
    }
    "$target/bin/conda-unpack"
done
while IFS= read -r archive; do
    [[ -n "$archive" ]] || continue
    archive_name="$(basename "$archive")"
    strip_components=0
    if [[ "$archive_name" == "model_fmt-triplet-v1.tar.zst" ]]; then
        target="$FMT_ROOT/models/fmt-triplet-v1"
    elif [[ "$archive_name" == "data_fmt-matching.tar.zst" ]]; then
        target="$WGS_FMT_MATCHING_DIR"
    else
        target="$DB_ROOT"
        strip_components=1
    fi
    printf 'INSPECT %s\n' "$archive"
    while IFS= read -r member; do
        if [[ "$member" == /* || "$member" == ../* || "$member" == */../* ]]; then
            printf 'Unsafe archive member rejected: %s\n' "$member" >&2
            exit 3
        fi
    done < <(zstd -dc -- "$archive" | tar -tf -)
    mkdir -p "$target"
    printf 'RESTORE %s -> %s\n' "$archive" "$target"
    zstd -dc -- "$archive" | tar -C "$target" --strip-components="$strip_components" -xf -
done < <(find "$BUNDLE_DIR" -maxdepth 1 -type f -name '*.tar.zst' -print | sort)

FMT_ROOT="$FMT_ROOT" "$SCRIPT_DIR/check-bioinformatics-runtime.sh"
