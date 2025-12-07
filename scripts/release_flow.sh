#!/usr/bin/env bash

set -euo pipefail

# Automated helper to:
# 1) Open/merge a PR from a feature branch into main
# 2) Bump version, tag, and create a GitHub release
# 3) Rebase the feature branch on the updated main
#
# Requirements:
# - gh CLI authenticated with repo scope
# - git + Python 3
#
# Usage:
#   scripts/release_flow.sh -b feature/branch -v 0.21.0 [-t "Release title"] [-n release_notes.md]

usage() {
  echo "Usage: $0 -b <branch> -v <version> [-t <title>] [-n <notes_file>]" >&2
  exit 1
}

BRANCH=""
VERSION=""
TITLE=""
NOTES_FILE=""

while getopts "b:v:t:n:" opt; do
  case "$opt" in
    b) BRANCH="$OPTARG" ;;
    v) VERSION="$OPTARG" ;;
    t) TITLE="$OPTARG" ;;
    n) NOTES_FILE="$OPTARG" ;;
    *) usage ;;
  esac
done

if [[ -z "$BRANCH" || -z "$VERSION" ]]; then
  usage
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install and authenticate first." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Using branch: $BRANCH, version: $VERSION"

# Ensure clean working tree
# Allow a single dirty file if it is the provided release notes path
if [[ -n "$(git status --porcelain)" ]]; then
  dirty="$(git status --porcelain)"
  allowed=0
  if [[ -n "$NOTES_FILE" ]]; then
    if [[ "$dirty" == "?? $NOTES_FILE"* || "$dirty" == " M $NOTES_FILE"* ]]; then
      allowed=1
    fi
  fi
  if [[ "$allowed" -eq 0 ]]; then
    echo "Working tree is dirty. Commit or stash changes first." >&2
    exit 1
  fi
fi

# 1) Create PR if missing and merge into main
git checkout "$BRANCH"
git pull --rebase

if ! gh pr view "$BRANCH" >/dev/null 2>&1; then
  echo "==> Creating PR from $BRANCH to main"
  gh pr create -B main -H "$BRANCH" -t "${TITLE:-Release $VERSION}" -b "Automated PR for release $VERSION"
else
  echo "==> PR already exists for $BRANCH"
fi

PR_STATE=""
if gh pr view "$BRANCH" >/dev/null 2>&1; then
  PR_STATE="$(gh pr view \"$BRANCH\" --json state --jq .state)"
fi

if [[ "$PR_STATE" == "MERGED" ]]; then
  echo "==> PR already merged; skipping merge step"
else
  echo "==> Merging PR"
  gh pr merge "$BRANCH" --merge
fi

# 2) Bump version on main, tag, and create release
git checkout main
git pull

echo "==> Bumping version to $VERSION"
VERSION="$VERSION" python3 - <<'PY'
from pathlib import Path
import re
path = Path("pyproject.toml")
text = path.read_text()
version = __import__("os").environ["VERSION"]
text = re.sub(r'^version\\s*=\\s*\"[^\"]+\"', f'version = "{version}"', text, flags=re.MULTILINE)
path.write_text(text)
PY

git status --short
git commit -am "Bump version to $VERSION"
git tag "v$VERSION"
git push origin main --follow-tags

echo "==> Creating GitHub release v$VERSION"
if [[ -n "$NOTES_FILE" ]]; then
  gh release create "v$VERSION" -t "${TITLE:-$VERSION}" -F "$NOTES_FILE"
else
  gh release create "v$VERSION" -t "${TITLE:-$VERSION}" -n "Release $VERSION"
fi

# 3) Rebase feature branch on updated main
git checkout "$BRANCH" || git checkout -b "$BRANCH"
git pull --rebase origin main
git push --force-with-lease origin "$BRANCH"

echo "==> Done. Branch $BRANCH rebased on main; main tagged v$VERSION."
