#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/linux-benchmark-lib"
STATE_FILE="${STATE_DIR}/grafana_install.json"

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "No Grafana install state found at ${STATE_FILE}."
  echo "If Grafana was installed manually, remove it with your system package manager."
  exit 1
fi

read_state_field() {
  local field="$1"
  python3 - <<PY
import json
import pathlib
state_file = pathlib.Path("${STATE_FILE}")
try:
    data = json.loads(state_file.read_text())
    print(data.get("${field}", "") or "")
except Exception:
    print("")
PY
}

METHOD="$(read_state_field "method")"
DATA_DIR="$(read_state_field "data_dir")"

if [[ -z "${METHOD}" ]]; then
  echo "Invalid Grafana install state file: ${STATE_FILE}"
  exit 1
fi

remove_data=""
print_usage() {
  cat <<EOF
Usage: uninstall_grafana.sh [--remove-data|--keep-data]

If no flag is provided, the script will prompt before removing data.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-data)
      remove_data="true"
      shift
      ;;
    --keep-data)
      remove_data="false"
      shift
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

if [[ -z "${remove_data}" ]]; then
  remove_data=false
  read -r -p "Remove Grafana data dir? [y/N]: " confirm
  case "${confirm}" in
    y|Y|yes|YES) remove_data=true ;;
    *) remove_data=false ;;
  esac
fi

case "${METHOD}" in
  brew)
    if command -v brew >/dev/null 2>&1; then
      brew services stop grafana >/dev/null 2>&1 || true
      brew uninstall grafana >/dev/null 2>&1 || true
    else
      echo "Homebrew not found. Please uninstall Grafana manually."
    fi
    ;;
  apt)
    if command -v systemctl >/dev/null 2>&1; then
      sudo systemctl stop grafana-server >/dev/null 2>&1 || true
      sudo systemctl disable grafana-server >/dev/null 2>&1 || true
    fi
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get remove -y grafana >/dev/null 2>&1 || true
    else
      echo "apt-get not found. Please uninstall Grafana manually."
    fi
    ;;
  docker)
    if command -v docker >/dev/null 2>&1; then
      docker rm -f grafana >/dev/null 2>&1 || true
    else
      echo "Docker not found. Please remove the Grafana container manually."
    fi
    ;;
  *)
    echo "Unknown install method '${METHOD}'."
    ;;
esac

if [[ "${remove_data}" == "true" ]]; then
  if [[ -n "${DATA_DIR}" && -d "${DATA_DIR}" ]]; then
    rm -rf "${DATA_DIR}"
  fi
  if [[ "${METHOD}" == "apt" && -d /etc/grafana ]]; then
    sudo rm -rf /etc/grafana
  fi
fi

rm -f "${STATE_FILE}"
echo "Grafana uninstall complete."
