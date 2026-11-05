#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
exec python3 "$SCRIPT_DIR/lib/install.py" "$@"
