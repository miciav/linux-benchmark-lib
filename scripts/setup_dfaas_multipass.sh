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

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
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
            "gateway_url": f"http://{target_ip}:31112",
            "prometheus_url": f"http://{target_ip}:30411",
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
    "workloads": {"dfaas": {"plugin": "dfaas", "enabled": True}},
}

config_path.write_text(json.dumps(config, indent=2))
print(f"Wrote {config_path}")
PY
}

main() {
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

  write_config "$target_ip" "$generator_ip"

  echo "Target VM: ${TARGET_NAME} (${target_ip})"
  echo "Generator VM: ${GENERATOR_NAME} (${generator_ip})"
  echo "Config file: ${CONFIG_PATH}"
}

main "$@"
