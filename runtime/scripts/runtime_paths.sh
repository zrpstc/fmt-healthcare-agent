#!/usr/bin/env bash
# Source this file after computing APP_ROOT; all data paths come from .env/environment.
_wgs_bootstrap_root="${WGS_ENV_ROOT:-$APP_ROOT/.venv}"
if [[ "$_wgs_bootstrap_root" != /* ]]; then
    _wgs_bootstrap_root="$APP_ROOT/$_wgs_bootstrap_root"
fi
_wgs_bootstrap_python="$_wgs_bootstrap_root/bin/python"
if [[ ! -x "$_wgs_bootstrap_python" ]]; then
    _wgs_bootstrap_python="$(command -v python3)"
fi
if ! _wgs_path_exports="$("$_wgs_bootstrap_python" "$APP_ROOT/scripts/runtime_paths.py" --shell)"; then
    printf 'Runtime path configuration could not be loaded.\n' >&2
    return 1
fi
eval "$_wgs_path_exports"
unset _wgs_bootstrap_root _wgs_bootstrap_python _wgs_path_exports

wgs_run_tool() {
    local prefix="$1"
    shift
    PATH="$prefix/bin${PATH:+:$PATH}" \
        LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$@"
}
