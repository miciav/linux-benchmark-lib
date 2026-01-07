#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TARGET_NAME="${DFAAS_TARGET_NAME:-dfaas-target}"
GENERATOR_NAME="${DFAAS_GENERATOR_NAME:-dfaas-generator}"
IMAGE="${DFAAS_MP_IMAGE:-24.04}"

TARGET_CPUS="${DFAAS_TARGET_CPUS:-4}"
TARGET_MEMORY="${DFAAS_TARGET_MEMORY:-8G}"
TARGET_DISK="${DFAAS_TARGET_DISK:-20G}"

GENERATOR_CPUS="${DFAAS_GENERATOR_CPUS:-2}"
GENERATOR_MEMORY="${DFAAS_GENERATOR_MEMORY:-4G}"
GENERATOR_DISK="${DFAAS_GENERATOR_DISK:-10G}"

KEY_DIR="${DFAAS_KEY_DIR:-${ROOT_DIR}/temp_keys}"
KEY_PATH="${DFAAS_KEY_PATH:-${KEY_DIR}/dfaas_multipass_key}"
PUB_KEY_PATH="${KEY_PATH}.pub"
TARGET_K6_KEY_PATH="${DFAAS_TARGET_K6_KEY_PATH:-/home/ubuntu/.ssh/dfaas_k6_key}"

CONFIG_PATH="${DFAAS_CONFIG_PATH:-${ROOT_DIR}/benchmark_config.dfaas_multipass.json}"
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

setup_k6_ssh() {
  local target_name="$1"
  local generator_name="$2"
  local key_path="$3"
  local pub_b64=""

  multipass exec "$target_name" -- bash -lc \
    "mkdir -p ~/.ssh && if [ ! -f '$key_path' ]; then ssh-keygen -t rsa -f '$key_path' -N ''; fi && chmod 600 '$key_path'"

  pub_b64="$(multipass exec "$target_name" -- base64 -w0 "${key_path}.pub")"
  multipass exec "$generator_name" -- bash -lc \
    "mkdir -p ~/.ssh && echo '$pub_b64' | base64 -d >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
}

write_config() {
  local target_ip="$1"
  local generator_ip="$2"

  DFAAS_TARGET_NAME="$TARGET_NAME" \
  DFAAS_TARGET_IP="$target_ip" \
  DFAAS_GENERATOR_IP="$generator_ip" \
  DFAAS_KEY_PATH="$KEY_PATH" \
  DFAAS_K6_KEY_PATH="$TARGET_K6_KEY_PATH" \
  DFAAS_LOKI_ENABLED="$ENABLE_LOKI" \
  DFAAS_LOKI_ENDPOINT="$LOKI_ENDPOINT" \
  DFAAS_CONFIG_PATH="$CONFIG_PATH" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

target_name = os.environ["DFAAS_TARGET_NAME"]
target_ip = os.environ["DFAAS_TARGET_IP"]
generator_ip = os.environ["DFAAS_GENERATOR_IP"]
key_path = os.environ["DFAAS_KEY_PATH"]
k6_key_path = os.environ["DFAAS_K6_KEY_PATH"]
config_path = Path(os.environ["DFAAS_CONFIG_PATH"])
loki_enabled = os.environ.get("DFAAS_LOKI_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
loki_endpoint = os.environ.get("DFAAS_LOKI_ENDPOINT", "").strip()

# We use {host.address} templates for URLs to support multi-target scenarios.
# These placeholders are resolved at runtime by the DFaaS generator.
config = {
    "remote_hosts": [
        {
            "name": target_name,
            "address": target_ip,
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
        "dfaas": {
            "k6_host": generator_ip,
            "k6_user": "ubuntu",
            "k6_ssh_key": k6_key_path,
            "k6_port": 22,
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
    "workloads": {"dfaas": {"plugin": "dfaas"}},
}

if loki_enabled:
    config["loki"] = {
        "enabled": True,
        "endpoint": loki_endpoint or "http://localhost:3100",
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
  ensure_vm "$TARGET_NAME" "$TARGET_CPUS" "$TARGET_MEMORY" "$TARGET_DISK"
  ensure_vm "$GENERATOR_NAME" "$GENERATOR_CPUS" "$GENERATOR_MEMORY" "$GENERATOR_DISK"

  inject_key "$TARGET_NAME"
  inject_key "$GENERATOR_NAME"
  setup_k6_ssh "$TARGET_NAME" "$GENERATOR_NAME" "$TARGET_K6_KEY_PATH"

  target_ip="$(wait_for_ip "$TARGET_NAME")"
  generator_ip="$(wait_for_ip "$GENERATOR_NAME")"
  
  if is_enabled "$ENABLE_LOKI"; then
    if [ -z "$LOKI_ENDPOINT" ]; then
      controller_ip="$(controller_ip_from_vm "$TARGET_NAME")"
      if [ -z "$controller_ip" ]; then
        controller_ip="$(controller_ip_local)"
      fi
      
      if [ -n "$controller_ip" ]; then
        LOKI_ENDPOINT="http://${controller_ip}:3100"
      else
        echo "WARNING: Could not determine controller IP for Loki." >&2
        echo "The remote runner may not be able to send logs." >&2
        echo "Please rerun with --loki-endpoint http://<YOUR_IP>:3100" >&2
        LOKI_ENDPOINT="http://localhost:3100"
      fi
    fi
  fi

  write_config "$target_ip" "$generator_ip"

  echo "Target VM: ${TARGET_NAME} (${target_ip})"
  echo "Generator VM: ${GENERATOR_NAME} (${generator_ip})"
  echo "Config file: ${CONFIG_PATH}"
}

main "$@"
