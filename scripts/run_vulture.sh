#!/usr/bin/env bash
set -euo pipefail

# Static dead-code scan with Vulture.
# Uses uv to ensure the project environment is leveraged.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

# Adjust the target list as needed; excluding .venv and build artifacts by default.
uv run vulture \
  lb_runner \
  lb_controller \
  lb_ui \
  lb_analytics \
  tests \
  --min-confidence 80
