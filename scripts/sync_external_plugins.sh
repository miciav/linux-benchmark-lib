#!/usr/bin/env bash

set -euo pipefail

# Sync external plugins (sysbench, unixbench) into lb_runner/plugins for local testing.
# Re-clones repos (main branch) and ensures .gitignore ignores them.
#
# Usage:
#   scripts/sync_external_plugins.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$ROOT/lb_runner/plugins"

declare -A REPOS=(
  ["sysbench-plugin"]="https://github.com/miciav/sysbench-plugin.git"
  ["unixbench-plugin"]="https://github.com/miciav/unixbench-plugin.git"
)

echo "Syncing external plugins into $PLUGIN_DIR"

for name in "${!REPOS[@]}"; do
  repo="${REPOS[$name]}"
  dest="$PLUGIN_DIR/$name"
  if [[ -d "$dest" ]]; then
    echo "Removing existing $dest"
    rm -rf "$dest"
  fi
  echo "Cloning $repo -> $dest"
  git clone --branch main --depth 1 "$repo" "$dest"
done

# Ensure .gitignore entries exist
IGNORE_ENTRIES=(
  "/lb_runner/plugins/sysbench-plugin/"
  "/lb_runner/plugins/unixbench-plugin/"
)

GITIGNORE="$ROOT/.gitignore"
touch "$GITIGNORE"
for entry in "${IGNORE_ENTRIES[@]}"; do
  if ! grep -Fxq "$entry" "$GITIGNORE"; then
    echo "$entry" >> "$GITIGNORE"
    echo "Added $entry to .gitignore"
  fi
done

echo "Done."
