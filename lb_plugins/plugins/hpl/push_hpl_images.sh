#!/usr/bin/env bash
set -euo pipefail

# Build and push HPL images (arm64/amd64) to Docker Hub.
# Usage: DOCKER_USER=youruser bash push_hpl_images.sh

if [ -z "${DOCKER_USER:-}" ]; then
  echo "Set DOCKER_USER to your Docker Hub username." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

DEB_ARM64_REL="${DEB_ARM64_REL:-lb_plugins/plugins/hpl/hpl_2.3-1_arm64.deb}"
DEB_AMD64_REL="${DEB_AMD64_REL:-lb_plugins/plugins/hpl/hpl_2.3-1_amd64.deb}"
DEB_ARM64="${ROOT_DIR}/${DEB_ARM64_REL}"
DEB_AMD64="${ROOT_DIR}/${DEB_AMD64_REL}"

if [ ! -f "$DEB_ARM64" ] || [ ! -f "$DEB_AMD64" ]; then
  echo "Missing .deb files: $DEB_ARM64 or $DEB_AMD64" >&2
  exit 1
fi

BUILDER="${BUILDER:-hpl-pusher}"

# Ensure buildx builder
if ! docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER" --use --bootstrap
else
  docker buildx use "$BUILDER"
fi

echo "Building and pushing ARM64..."
docker buildx build --platform linux/arm64 \
  -f "${ROOT_DIR}/lb_plugins/plugins/hpl/Dockerfile.arm" \
  --build-arg HPL_DEB="${DEB_ARM64_REL}" \
  --no-cache \
  -t "${DOCKER_USER}/hpl:2.3-arm64" \
  --push \
  "${ROOT_DIR}"

echo "Building and pushing AMD64..."
docker buildx build --platform linux/amd64 \
  -f "${ROOT_DIR}/lb_plugins/plugins/hpl/Dockerfile.amd64" \
  --build-arg HPL_DEB="${DEB_AMD64_REL}" \
  --no-cache \
  -t "${DOCKER_USER}/hpl:2.3-amd64" \
  --push \
  "${ROOT_DIR}"

echo "Creating and pushing multi-arch manifest..."
docker manifest create "${DOCKER_USER}/hpl:2.3" \
  --amend "${DOCKER_USER}/hpl:2.3-arm64" \
  --amend "${DOCKER_USER}/hpl:2.3-amd64"

docker manifest push "${DOCKER_USER}/hpl:2.3"

echo "Done. Pushed tags:"
echo "  ${DOCKER_USER}/hpl:2.3-arm64"
echo "  ${DOCKER_USER}/hpl:2.3-amd64"
echo "  ${DOCKER_USER}/hpl:2.3 (multi-arch manifest)"
