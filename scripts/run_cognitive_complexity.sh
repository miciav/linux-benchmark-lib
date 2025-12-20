#!/usr/bin/env bash
set -euo pipefail

# Run flake8-cognitive-complexity across the codebase.
# MAX_COG_COMPLEXITY can override the default threshold (15).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

THRESHOLD="${MAX_COG_COMPLEXITY:-15}"
TARGETS=(
  lb_runner
  lb_controller
  lb_ui
  lb_analytics
  tests
)

uv run flake8 \
  --max-cognitive-complexity "${THRESHOLD}" \
  --select CCR001 \
  "${TARGETS[@]}" \
  "$@"
