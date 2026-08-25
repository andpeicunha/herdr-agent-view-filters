#!/usr/bin/env bash
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
exec python3 "$dir/bin/agent_view.py" "${1:-cycle}"
