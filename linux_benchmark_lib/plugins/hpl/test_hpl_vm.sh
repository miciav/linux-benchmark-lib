#!/usr/bin/env bash
set -euo pipefail

# Spin up a Multipass VM, install deps, install a provided HPL .deb,
# drop a sample HPL.dat, and run xhpl.
#
# Usage: bash test_hpl_vm.sh /path/to/hpl_2.3-1_*.deb

if [ $# -lt 1 ]; then
  echo "Usage: $0 /path/to/hpl_2.3-1_*.deb" >&2
  exit 1
fi

DEB_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
if [ ! -f "$DEB_PATH" ]; then
  echo "Deb file not found: $DEB_PATH" >&2
  exit 1
fi

VM_NAME="${VM_NAME:-hpl-test}"
HPL_DAT_CONTENT="HPLinpack benchmark input file
Innovative Computing Laboratory, University of Tennessee
HPL.out      output file name (if any)
6            device out (6=stdout,7=stderr,file)
1            # of problems sizes (N)
5000         Ns
1            # of NBs
128          NBs
0            PMAP process mapping (0=Row-,1=Column-major)
1            # of process grids (P x Q)
1            Ps
1            Qs
16.0         threshold
1            # of panel fact
2            PFACTs (0=left, 1=Crout, 2=Right)
1            # of recursive stopping criterium
4            NBMINs (>= 1)
1            # of panels in recursion
2            NDIVs
1            # of recursive panel fact.
1            RFACTs (0=left, 1=Crout, 2=Right)
1            # of broadcast
1            BCASTs (0=1rg,1=1rM,2=2rg,3=2rM,4=Lng,5=LnM)
1            # of lookahead depth
1            DEPTHs (>=0)
2            SWAP (0=bin-exch,1=long,2=mix)
64           swapping threshold
0            L1 in (0=transposed,1=no-transposed) form
0            U  in (0=transposed,1=no-transposed) form
1            Equilibration (0=no,1=yes)
8            memory alignment in double (> 0)
"

# Clean existing VM with same name
if multipass info "$VM_NAME" >/dev/null 2>&1; then
  multipass delete "$VM_NAME"
  multipass purge
fi

echo "Launching VM $VM_NAME..."
multipass launch -n "$VM_NAME" --memory 4G --disk 10G --cpus 2

echo "Installing runtime deps..."
multipass exec "$VM_NAME" -- bash -lc "sudo apt-get update && sudo apt-get install -y \
  openmpi-bin libopenmpi-dev libopenblas-dev && sudo apt-get clean"

echo "Transferring deb..."
multipass transfer "$DEB_PATH" "$VM_NAME":/home/ubuntu/

echo "Installing deb..."
multipass exec "$VM_NAME" -- bash -lc "sudo dpkg -i /home/ubuntu/$(basename "$DEB_PATH") || sudo apt-get -f install -y"

echo "Writing HPL.dat..."
HPL_DIR="/opt/hpl-2.3/bin/Linux"
multipass exec "$VM_NAME" -- bash -lc "sudo mkdir -p ${HPL_DIR} && sudo tee ${HPL_DIR}/HPL.dat >/dev/null <<'EOF'
${HPL_DAT_CONTENT}
EOF"

echo "Running xhpl smoke test..."
multipass exec "$VM_NAME" -- bash -lc "cd ${HPL_DIR} && mpirun --allow-run-as-root -np 1 ./xhpl"

echo "Done. VM: $VM_NAME"
