#!/usr/bin/env bash
set -euo pipefail

# Build HPL .deb for a target architecture using Docker Buildx.
# Requires Docker Buildx with binfmt/qemu for cross-platform builds.
#
# Usage: TARGET_ARCH=linux/amd64 bash build_hpl_docker_cross.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DOCKERFILE="${REPO_ROOT}/linux_benchmark_lib/plugins/hpl/Dockerfile.cross"
TARGET_ARCH="${TARGET_ARCH:-linux/amd64}"
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/out-${TARGET_ARCH//\//-}}"
BUILDER="${BUILDER:-hpl-cross-builder}"

if [ ! -f "$DOCKERFILE" ]; then
  echo "Dockerfile.cross not found at $DOCKERFILE" >&2
  exit 1
fi

# Ensure buildx builder exists
if ! docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER" --use
else
  docker buildx use "$BUILDER"
fi

echo "Building for $TARGET_ARCH -> $OUT_DIR"
mkdir -p "$OUT_DIR"

docker buildx build \
  --platform "$TARGET_ARCH" \
  --output type=local,dest="$OUT_DIR" \
  -f "$DOCKERFILE" \
  "$REPO_ROOT"

echo "Artifacts in: $OUT_DIR"
ls -l "$OUT_DIR" || true
