#!/usr/bin/env bash
set -euo pipefail

worktree_path="${1:-}"
if [[ -z "$worktree_path" ]]; then
  echo "Usage: $0 /path/to/worktree" >&2
  exit 2
fi

if [[ ! -d "$worktree_path" ]]; then
  echo "Worktree not found: $worktree_path" >&2
  exit 2
fi

# Deinit submodules inside the worktree first to avoid git worktree remove failures.
git -C "$worktree_path" submodule deinit -f --all || true

# Remove the worktree; --force handles leftover submodule metadata.
git worktree remove --force "$worktree_path"
