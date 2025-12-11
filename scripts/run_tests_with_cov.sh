#!/usr/bin/env bash
set -euo pipefail

# Run pytest with coverage for all core packages.
# Usage: scripts/run_tests_with_cov.sh [pytest args...]

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; install uv or adjust this script to your environment." >&2
  exit 1
fi

EXTRAS=".[dev]"
PYTEST_ARGS=("$@")

uv run --extra dev pytest \
  --cov=lb_runner \
  --cov=lb_controller \
  --cov=lb_ui \
  --cov=lb_analytics \
  --cov-report=term-missing \
  "${PYTEST_ARGS[@]}"
