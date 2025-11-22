#!/usr/bin/env bash
set -euo pipefail

# macOS helper to start Docker Desktop (if needed) and run the containerized tests.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

require_docker() {
  if docker info >/dev/null 2>&1; then
    echo "✅ Docker Desktop is running."
    return
  fi

  echo "⏳ Starting Docker Desktop..."
  if command -v open >/dev/null 2>&1; then
    open -a Docker >/dev/null 2>&1 || true
  else
    echo "⚠️  Cannot auto-start Docker Desktop (no 'open'); start it manually and re-run." >&2
    exit 1
  fi

  printf "   Waiting for Docker to be ready"
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      echo " done."
      return
    fi
    printf "."
    sleep 2
  done
  echo
  echo "❌ Docker did not become ready within 120s. Please start Docker Desktop and retry." >&2
  exit 1
}

require_docker

cd "${REPO_ROOT}"
echo "🏗️  Building test image and running tests via Docker..."
bash "${REPO_ROOT}/run_tests.sh"
