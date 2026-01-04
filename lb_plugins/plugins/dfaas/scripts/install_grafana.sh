#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/linux-benchmark-lib"
STATE_FILE="${STATE_DIR}/grafana_install.json"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/grafana"

mkdir -p "${STATE_DIR}" "${DATA_DIR}"

write_state() {
  local method="$1"
  local data_dir="$2"
  cat <<EOF >"${STATE_FILE}"
{"method":"${method}","data_dir":"${data_dir}"}
EOF
}

verify_grafana() {
  if command -v curl >/dev/null 2>&1; then
    if curl -sf "http://localhost:3000/api/health" >/dev/null; then
      echo "Grafana is responding on http://localhost:3000"
      return 0
    fi
  fi
  if command -v grafana-server >/dev/null 2>&1; then
    grafana-server -v >/dev/null 2>&1 || true
  fi
  echo "Grafana installation completed. Verify at http://localhost:3000"
}

install_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew not found. Install it first: https://brew.sh/"
    exit 1
  fi
  brew install grafana
  if command -v brew >/dev/null 2>&1; then
    brew services start grafana >/dev/null 2>&1 || true
  fi
  write_state "brew" ""
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
    if [[ "${VERSION_ID:-}" < "24.04" ]]; then
      echo "Ubuntu 24.04+ is required for the apt install option."
      exit 1
    fi
  fi
  sudo apt-get update
  sudo apt-get install -y grafana
  sudo systemctl enable --now grafana-server >/dev/null 2>&1 || true
  write_state "apt" ""
}

install_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not found. Install Docker first."
    exit 1
  fi
  docker rm -f grafana >/dev/null 2>&1 || true
  docker run -d \
    --name grafana \
    --restart unless-stopped \
    -p 3000:3000 \
    -v "${DATA_DIR}:/var/lib/grafana" \
    grafana/grafana:latest >/dev/null
  write_state "docker" "${DATA_DIR}"
}

choose_method() {
  local os
  os="$(uname -s)"
  echo "Select Grafana install method:"
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

choose_method
verify_grafana
