#!/usr/bin/env bash
set -euo pipefail

mode="${1-}"

usage() {
  cat <<'EOF'
Usage: bash tools/switch_mode.sh <mode>

Modes:
  base        uv sync (core only)
  controller  uv sync --extra controller
  dev         uv sync --all-extras --dev

Re-syncs the current virtual environment with the selected dependency set.
EOF
}

if [[ -z "${mode}" ]]; then
  usage
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found in PATH" >&2
  exit 1
fi

case "${mode}" in
  base)
    echo "[info] Syncing base deps"
    uv sync
    rm -f .lb_dev_cli
    ;;
  controller)
    echo "[info] Syncing controller deps"
    uv sync --extra controller
    rm -f .lb_dev_cli
    ;;
  dev)
    echo "[info] Syncing dev deps"
    uv sync --all-extras --dev
    touch .lb_dev_cli
    ;;
  *)
    echo "Unknown mode: ${mode}" >&2
    usage
    exit 1
    ;;
esac

echo "[info] Done"
