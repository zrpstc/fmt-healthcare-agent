#!/usr/bin/env bash
# Compatibility entry point. The historical one-time migration is archived in deploy/legacy/.
set -euo pipefail
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/project.sh" restart "$@"
