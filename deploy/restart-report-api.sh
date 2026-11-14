#!/usr/bin/env bash
set -euo pipefail
# Keep the report API scope last so caller options cannot broaden this restart.
exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/command.sh" restart "$@" --component workspace-api
