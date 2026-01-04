#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/linux-benchmark-lib"
STATE_FILE="${STATE_DIR}/loki_install.json"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/loki"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/loki"
CONFIG_FILE="${CONFIG_DIR}/loki-config.yaml"

mkdir -p "${STATE_DIR}" "${CONFIG_DIR}" "${DATA_DIR}"

version_gte() {
  # Returns 0 (true) if $1 >= $2 using version sorting
  local v1="$1" v2="$2"
  [[ "$(printf '%s\n%s' "$v2" "$v1" | sort -V | head -n1)" == "$v2" ]]
}

write_default_config() {
  if [[ -f "${CONFIG_FILE}" ]]; then
    return
  fi
  cat <<EOF >"${CONFIG_FILE}"
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: ${DATA_DIR}
  storage:
    filesystem:
      chunks_directory: ${DATA_DIR}/chunks
      rules_directory: ${DATA_DIR}/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093
EOF
}

verify_loki() {
  if command -v curl >/dev/null 2>&1; then
    if curl -sf "http://localhost:3100/ready" >/dev/null; then
      echo "Loki is responding on http://localhost:3100"
      return 0
    fi
  fi
  if command -v loki >/dev/null 2>&1; then
    loki --version >/dev/null 2>&1 || true
  fi
  echo "Loki installation completed. Verify at http://localhost:3100/ready"
}

write_state() {
  local method="$1"
  cat <<EOF >"${STATE_FILE}"
{"method":"${method}","config_file":"${CONFIG_FILE}","data_dir":"${DATA_DIR}"}
EOF
}

brew_formula_exists() {
  local formula="$1"
  brew info "${formula}" >/dev/null 2>&1
}

install_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew not found. Install it first: https://brew.sh/"
    exit 1
  fi
  write_default_config
  local formula="loki"
  if ! brew_formula_exists "${formula}"; then
    brew tap grafana/tap >/dev/null 2>&1 || true
    if brew_formula_exists "grafana/tap/loki"; then
      formula="grafana/tap/loki"
    else
      echo "Loki formula not found in Homebrew. Try the docker install option."
      exit 1
    fi
  fi
  brew install "${formula}"
  if command -v brew >/dev/null 2>&1; then
    brew services start "${formula}" >/dev/null 2>&1 || true
  fi
  write_state "brew"
}

install_apt() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found. This option is for Ubuntu 24.04+."
    exit 1
  fi
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" ]]; then
      echo "This script supports apt on Ubuntu 24.04+ only."
      exit 1
    fi
    if ! version_gte "${VERSION_ID:-0}" "24.04"; then
      echo "Ubuntu 24.04+ is required for the apt install option."
      exit 1
    fi
  fi
  write_default_config
  sudo apt-get update
  sudo apt-get install -y loki
  if [[ -d /etc/loki ]]; then
    sudo cp "${CONFIG_FILE}" /etc/loki/config.yml
  fi
  sudo systemctl enable --now loki >/dev/null 2>&1 || true
  write_state "apt"
}

install_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not found. Install Docker first."
    exit 1
  fi
  write_default_config
  docker rm -f loki >/dev/null 2>&1 || true
  docker run -d \
    --name loki \
    --restart unless-stopped \
    -p 3100:3100 \
    -v "${CONFIG_FILE}:/etc/loki/local-config.yaml:ro" \
    -v "${DATA_DIR}:/loki" \
    grafana/loki:latest \
    -config.file=/etc/loki/local-config.yaml >/dev/null
  write_state "docker"
}

choose_method() {
  local os
  os="$(uname -s)"
  echo "Select Loki install method:"
  if [[ "${os}" == "Darwin" ]]; then
    echo "  1) brew (macOS)"
    echo "  2) docker (macOS/Linux)"
    read -r -p "Choice [1-2]: " choice
    case "${choice}" in
      1|"") install_brew ;;
      2) install_docker ;;
      *) echo "Invalid choice"; exit 1 ;;
    esac
  elif [[ "${os}" == "Linux" ]]; then
    echo "  1) apt (Ubuntu 24.04+)"
    echo "  2) docker (macOS/Linux)"
    read -r -p "Choice [1-2]: " choice
    case "${choice}" in
      1|"") install_apt ;;
      2) install_docker ;;
      *) echo "Invalid choice"; exit 1 ;;
    esac
  else
    echo "Unsupported OS: ${os}"
    exit 1
  fi
}

run_mode() {
  local mode="$1"
  local os
  os="$(uname -s)"
  case "${mode}" in
    local)
      if [[ "${os}" == "Darwin" ]]; then
        install_brew
      elif [[ "${os}" == "Linux" ]]; then
        install_apt
      else
        echo "Unsupported OS: ${os}"
        exit 1
      fi
      ;;
    brew)
      install_brew
      ;;
    apt)
      install_apt
      ;;
    docker)
      install_docker
      ;;
    *)
      echo "Unsupported mode: ${mode}"
      exit 1
      ;;
  esac
}

print_usage() {
  cat <<EOF
Usage: install_loki.sh [--mode local|docker|brew|apt]

If --mode is omitted, the script will prompt for an install method.
EOF
}

MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      print_usage
      exit 1
      ;;
  esac
done

if [[ -n "${MODE}" ]]; then
  run_mode "${MODE}"
else
  choose_method
fi
verify_loki
