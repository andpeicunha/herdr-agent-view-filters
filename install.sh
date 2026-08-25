#!/usr/bin/env bash
set -euo pipefail
plugin_dir="${HERDR_PLUGIN_DIR:-${1:-$HOME/.config/herdr/plugins}}"
target="$plugin_dir/agent-view-filters"
source_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

mkdir -p "$target/bin"
cp "$source_dir/herdr-plugin.toml" "$source_dir/run.sh" "$target/"
cp "$source_dir/bin/agent_view.py" "$target/bin/"
chmod +x "$target/run.sh" "$target/bin/agent_view.py"

printf 'installed andpeicunha.agent-view-filters to %s\n' "$target"
