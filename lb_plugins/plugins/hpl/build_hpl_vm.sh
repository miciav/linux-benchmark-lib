#!/usr/bin/env bash
set -euo pipefail

# Create a Multipass VM, install build deps, copy packaging files, and
# build the HPL .deb (binary only). Assumes this script is run from the repo root.
# Optional: set VM_ARCH (e.g., x86_64 or aarch64) to override default arch.

VM_NAME="${VM_NAME:-hpl-build}"
VM_ARCH="${VM_ARCH:-}"
HPL_URL="http://www.netlib.org/benchmark/hpl/hpl-2.3.tar.gz"
WORKDIR="/home/ubuntu/hpl-deb"
PKGDIR="${WORKDIR}/hpl-2.3"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
MAKE_FILE="${REPO_ROOT}/lb_plugins/plugins/hpl/Make.Linux"
CONTROL_FILE="${REPO_ROOT}/lb_plugins/plugins/hpl/control"
RULES_FILE="${REPO_ROOT}/lb_plugins/plugins/hpl/rules"

# Validate files before launching
for f in "$MAKE_FILE" "$CONTROL_FILE" "$RULES_FILE"; do
  if [ ! -f "$f" ]; then
    echo "Missing required file: $f" >&2
    exit 1
  fi
done

# Delete any existing VM with the same name
if multipass info "$VM_NAME" >/dev/null 2>&1; then
  multipass delete "$VM_NAME"
  multipass purge
fi

echo "Launching VM $VM_NAME..."
if [ -n "$VM_ARCH" ]; then
  if multipass launch --help 2>/dev/null | grep -q -- "--arch"; then
    multipass launch -n "$VM_NAME" --memory 10G --disk 40G --cpus 4 --arch "$VM_ARCH"
  else
    echo "This Multipass version does not support --arch; cannot launch $VM_ARCH VM." >&2
    exit 1
  fi
else
  multipass launch -n "$VM_NAME" --memory 10G --disk 40G --cpus 4
fi

echo "Installing build dependencies..."
multipass exec "$VM_NAME" -- bash -lc "sudo apt-get update && sudo apt-get install -y \
  build-essential gfortran openmpi-bin libopenmpi-dev libopenblas-dev make wget tar \
  devscripts debhelper dh-python"

echo "Preparing sources..."
multipass exec "$VM_NAME" -- bash -lc "mkdir -p $WORKDIR && cd $WORKDIR && \
  wget -q $HPL_URL && tar xf hpl-2.3.tar.gz"
multipass exec "$VM_NAME" -- bash -lc "mkdir -p $PKGDIR/debian"

echo "Copying Make.Linux, control, and rules..."
multipass transfer "$MAKE_FILE"   "$VM_NAME":"$PKGDIR"/Make.Linux
multipass transfer "$CONTROL_FILE" "$VM_NAME":"$PKGDIR"/debian/control
multipass transfer "$RULES_FILE"   "$VM_NAME":"$PKGDIR"/debian/rules
multipass exec "$VM_NAME" -- bash -lc "cd $PKGDIR && chmod +x debian/rules"

echo "Changelog..."
multipass exec "$VM_NAME" -- bash -lc "cd $PKGDIR && \
  DEBFULLNAME='HPL Builder' DEBEMAIL='builder@example.com' \
  dch --create -v 2.3-1 --package hpl 'Initial package.'"

echo "Building .deb (binary only)..."
multipass exec "$VM_NAME" -- bash -lc "cd $PKGDIR && dpkg-buildpackage -b -us -uc -Zgzip -z3"

echo "Artifacts:"
multipass exec "$VM_NAME" -- bash -lc "ls -l ${WORKDIR}/*.deb"

echo "Done. Optionally copy the deb to host with:"
echo "multipass transfer ${VM_NAME}:${WORKDIR}/hpl_2.3-1_*.deb ."
