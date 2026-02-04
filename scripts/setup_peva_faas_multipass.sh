#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RUNNER_NAME="${PEVA_FAAS_RUNNER_NAME:-peva-faas-runner}"
K3S_NAME="${PEVA_FAAS_K3S_NAME:-peva-faas-k3s}"
IMAGE="${PEVA_FAAS_MP_IMAGE:-24.04}"

RUNNER_CPUS="${PEVA_FAAS_RUNNER_CPUS:-2}"
RUNNER_MEMORY="${PEVA_FAAS_RUNNER_MEMORY:-4G}"
RUNNER_DISK="${PEVA_FAAS_RUNNER_DISK:-10G}"

K3S_CPUS="${PEVA_FAAS_K3S_CPUS:-4}"
K3S_MEMORY="${PEVA_FAAS_K3S_MEMORY:-8G}"
K3S_DISK="${PEVA_FAAS_K3S_DISK:-20G}"

KEY_DIR="${PEVA_FAAS_KEY_DIR:-${ROOT_DIR}/temp_keys}"
KEY_PATH="${PEVA_FAAS_KEY_PATH:-${KEY_DIR}/peva_faas_multipass_key}"
PUB_KEY_PATH="${KEY_PATH}.pub"

CONFIG_PATH="${PEVA_FAAS_CONFIG_PATH:-${ROOT_DIR}/benchmark_config.peva_faas_multipass.json}"
ENABLE_LOKI="1"
LOKI_ENDPOINT=""

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  --loki                Enable Loki (default)
  --no-loki             Disable Loki
  --loki-endpoint URL   Loki endpoint (e.g. http://<controller-ip>:3100)
  -h, --help            Show this help message
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --loki)
        ENABLE_LOKI="1"
        shift
        ;;
      --no-loki)
        ENABLE_LOKI="0"
        shift
        ;;
      --loki-endpoint)
        if [ -z "${2:-}" ]; then
          echo "Missing value for --loki-endpoint" >&2
          exit 1
        fi
        LOKI_ENDPOINT="$2"
        shift 2
        ;;
      --loki-endpoint=*)
        LOKI_ENDPOINT="${1#*=}"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

ensure_keypair() {
  if [ ! -f "$KEY_PATH" ]; then
    mkdir -p "$KEY_DIR"
    ssh-keygen -t rsa -f "$KEY_PATH" -N "" >/dev/null
  fi
  if [ ! -f "$PUB_KEY_PATH" ]; then
    ssh-keygen -y -f "$KEY_PATH" > "$PUB_KEY_PATH"
  fi
  chmod 600 "$KEY_PATH"
}

vm_exists() {
  multipass info "$1" >/dev/null 2>&1
}

vm_state() {
  local name="$1"
  multipass info "$name" --format json | python3 -c \
    'import json, sys; info=json.load(sys.stdin); name=sys.argv[1]; print(info["info"][name]["state"])' \
    "$name"
}

ensure_vm() {
  local name="$1"
  local cpus="$2"
  local memory="$3"
  local disk="$4"

  if vm_exists "$name"; then
    echo "VM ${name} already exists; skipping launch."
  else
    multipass launch --name "$name" --cpus "$cpus" --memory "$memory" --disk "$disk" "$IMAGE"
  fi

  if [ "$(vm_state "$name")" != "Running" ]; then
    multipass start "$name"
  fi
}

vm_ip() {
  local name="$1"
  multipass info "$name" --format json | python3 -c \
    'import json, sys; info=json.load(sys.stdin); name=sys.argv[1]; ips=info["info"][name]["ipv4"]; print(ips[0] if ips else "")' \
    "$name"
}

wait_for_ip() {
  local name="$1"
  local ip=""
  for _ in $(seq 1 20); do
    ip="$(vm_ip "$name")"
    if [ -n "$ip" ]; then
      echo "$ip"
      return 0
    fi
    sleep 2
  done
  echo "Unable to retrieve IP for ${name}" >&2
  return 1
}

is_enabled() {
  local raw="${1:-}"
  local lower
  lower="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

controller_ip_from_vm() {
  local name="$1"
  multipass exec "$name" -- bash -lc "ip route | awk '/default/ {print \$3; exit}'" 2>/dev/null || true
}

controller_ip_local() {
  local os
  os="$(uname -s)"
  if [ "${os}" = "Darwin" ]; then
    local iface=""
    iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
    if [ -n "$iface" ] && command -v ipconfig >/dev/null 2>&1; then
      ipconfig getifaddr "$iface" 2>/dev/null || true
      return 0
    fi
  else
    if command -v ip >/dev/null 2>&1; then
      ip route get 1 2>/dev/null | awk '{print $7; exit}'
      return 0
    fi
    if command -v hostname >/dev/null 2>&1; then
      hostname -I 2>/dev/null | awk '{print $1; exit}'
      return 0
    fi
  fi
  echo ""
}

inject_key() {
  local name="$1"
  local pub_key
  pub_key="$(cat "$PUB_KEY_PATH")"
  multipass exec "$name" -- bash -lc \
    "mkdir -p ~/.ssh && echo '$pub_key' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
}

write_config() {
  local runner_ip="$1"
  local k3s_ip="$2"

  PEVA_FAAS_RUNNER_NAME="$RUNNER_NAME" \
  PEVA_FAAS_RUNNER_IP="$runner_ip" \
  PEVA_FAAS_K3S_IP="$k3s_ip" \
  PEVA_FAAS_KEY_PATH="$KEY_PATH" \
  PEVA_FAAS_LOKI_ENABLED="$ENABLE_LOKI" \
  PEVA_FAAS_LOKI_ENDPOINT="$LOKI_ENDPOINT" \
  PEVA_FAAS_CONFIG_PATH="$CONFIG_PATH" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

runner_name = os.environ["PEVA_FAAS_RUNNER_NAME"]
runner_ip = os.environ["PEVA_FAAS_RUNNER_IP"]
k3s_ip = os.environ["PEVA_FAAS_K3S_IP"]
key_path = os.environ["PEVA_FAAS_KEY_PATH"]
config_path = Path(os.environ["PEVA_FAAS_CONFIG_PATH"])
loki_enabled = os.environ.get("PEVA_FAAS_LOKI_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
loki_endpoint = os.environ.get("PEVA_FAAS_LOKI_ENDPOINT", "").strip()

config = {
    "remote_hosts": [
        {
            "name": runner_name,
            "address": runner_ip,
            "user": "ubuntu",
            "become": True,
            "vars": {
                "ansible_ssh_private_key_file": key_path,
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                "ansible_python_interpreter": "/usr/bin/python3",
            },
        }
    ],
    "remote_execution": {"enabled": True},
    "plugin_settings": {
        "peva_faas": {
            "k3s_host": k3s_ip,
            "k3s_user": "ubuntu",
            "k3s_ssh_key": key_path,
            "k3s_port": 22,
            "gateway_url": "http://{host.address}:31112",
            "prometheus_url": "http://{host.address}:30411",
            "functions": [
                {
                    "name": "env",
                    "method": "GET",
                    "body": "",
                    "headers": {"Authorization": "Basic CHANGE_ME"},
                }
            ],
        }
    },
    "workloads": {
        "peva_faas": {
            "plugin": "peva_faas",
            "collectors_enabled": False,
        }
    },
}

if loki_enabled:
    resolved_endpoint = loki_endpoint or "http://localhost:3100"
    config["loki"] = {
        "enabled": True,
        "endpoint": resolved_endpoint,
    }
    config["plugin_settings"]["peva_faas"]["loki"] = {
        "enabled": True,
        "endpoint": resolved_endpoint,
    }

config_path.write_text(json.dumps(config, indent=2))
print(f"Wrote {config_path}")
PY
}

main() {
  parse_args "$@"

  require_cmd multipass
  require_cmd ssh-keygen
  require_cmd python3

  ensure_keypair
  ensure_vm "$RUNNER_NAME" "$RUNNER_CPUS" "$RUNNER_MEMORY" "$RUNNER_DISK"
  ensure_vm "$K3S_NAME" "$K3S_CPUS" "$K3S_MEMORY" "$K3S_DISK"

  inject_key "$RUNNER_NAME"
  inject_key "$K3S_NAME"

  runner_ip="$(wait_for_ip "$RUNNER_NAME")"
  k3s_ip="$(wait_for_ip "$K3S_NAME")"

  if is_enabled "$ENABLE_LOKI"; then
    if [ -z "$LOKI_ENDPOINT" ]; then
      controller_ip="$(controller_ip_from_vm "$RUNNER_NAME")"
      if [ -z "$controller_ip" ]; then
        controller_ip="$(controller_ip_local)"
      fi

      if [ -n "$controller_ip" ]; then
        LOKI_ENDPOINT="http://${controller_ip}:3100"
      else
        echo "WARNING: Could not determine controller IP for Loki." >&2
        echo "The runner may not be able to send logs." >&2
        echo "Please rerun with --loki-endpoint http://<YOUR_IP>:3100" >&2
        LOKI_ENDPOINT="http://localhost:3100"
      fi
    fi
  fi

  write_config "$runner_ip" "$k3s_ip"

  echo "Runner VM: ${RUNNER_NAME} (${runner_ip})"
  echo "K3s VM: ${K3S_NAME} (${k3s_ip})"
  echo "Config file: ${CONFIG_PATH}"
}

main "$@"
