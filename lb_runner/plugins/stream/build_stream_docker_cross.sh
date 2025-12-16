#!/usr/bin/env bash
set -euo pipefail

# Build stream-benchmark .deb for a target architecture using Docker Buildx.
#
# Usage: TARGET_ARCH=linux/amd64 bash lb_runner/plugins/stream/build_stream_docker_cross.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DOCKERFILE="${REPO_ROOT}/lb_runner/plugins/stream/Dockerfile.cross"
TARGET_ARCH="${TARGET_ARCH:-linux/amd64}"
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/out-${TARGET_ARCH//\//-}-stream}"
BUILDER="${BUILDER:-stream-cross-builder}"

if [ ! -f "$DOCKERFILE" ]; then
  echo "Dockerfile.cross not found at $DOCKERFILE" >&2
  exit 1
fi

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

