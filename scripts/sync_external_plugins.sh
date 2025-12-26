#!/usr/bin/env bash

set -euo pipefail

# Sync external plugins (sysbench, unixbench) into the user plugin directory for
# local testing.
#
# This writes into `lb_plugins/plugins/_user` by default, matching the plugin
# registry's preferred user plugin dir when the source tree is writable.
#
# Re-clones repos and ensures `.gitignore` ignores the target dir.
#
# Usage:
#   scripts/sync_external_plugins.sh
#   scripts/sync_external_plugins.sh --branch main
#   scripts/sync_external_plugins.sh --dest /path/to/plugins

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILTIN_PLUGIN_DIR="$ROOT/lb_plugins/plugins"
DEFAULT_USER_PLUGIN_DIR="$BUILTIN_PLUGIN_DIR/_user"
PATCH_DIR="$ROOT/scripts/external_plugin_patches"

BRANCH=""
DEST="$DEFAULT_USER_PLUGIN_DIR"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --dest)
      DEST="${2:-}"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--branch BRANCH] [--dest DIR]"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if ! command -v git >/dev/null 2>&1; then
  echo "git is required (not found in PATH)" >&2
  exit 1
fi

mkdir -p "$DEST"

REPOS=(
  "sysbench-plugin=https://github.com/miciav/sysbench-plugin.git"
  "unixbench-plugin=https://github.com/miciav/unixbench-plugin.git"
)

echo "Syncing external plugins into $DEST"

for spec in "${REPOS[@]}"; do
  name="${spec%%=*}"
  repo="${spec#*=}"
  dest="$DEST/$name"
  if [[ -d "$dest" ]]; then
    echo "Removing existing $dest"
    rm -rf "$dest"
  fi
  echo "Cloning $repo -> $dest"
  if [[ -n "$BRANCH" ]]; then
    git clone --branch "$BRANCH" --depth 1 "$repo" "$dest"
  else
    git clone --depth 1 "$repo" "$dest"
  fi

  patch_file="$PATCH_DIR/${name}.patch"
  if [[ -f "$patch_file" ]]; then
    echo "Applying local port patch: $patch_file"
    if git -C "$dest" apply --check "$patch_file" >/dev/null 2>&1; then
      git -C "$dest" apply "$patch_file"
    elif git -C "$dest" apply -R --check "$patch_file" >/dev/null 2>&1; then
      echo "Patch already applied for $name"
    else
      echo "Patch does not apply cleanly for $name: $patch_file" >&2
      exit 1
    fi
  fi

  # Some external repos accidentally commit Python bytecode caches. Ensure our
  # workspace stays clean and deterministic.
  find "$dest" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
  find "$dest" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
done

# Ensure .gitignore entries exist
IGNORE_ENTRIES=("/lb_plugins/plugins/_user/")

GITIGNORE="$ROOT/.gitignore"
touch "$GITIGNORE"
for entry in "${IGNORE_ENTRIES[@]}"; do
  if ! grep -Fxq "$entry" "$GITIGNORE"; then
    echo "$entry" >> "$GITIGNORE"
    echo "Added $entry to .gitignore"
  fi
done

echo "Done."
