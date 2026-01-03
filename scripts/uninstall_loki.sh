#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/linux-benchmark-lib"
STATE_FILE="${STATE_DIR}/loki_install.json"

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "No Loki install state found at ${STATE_FILE}."
  echo "If Loki was installed manually, remove it with your system package manager."
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
CONFIG_FILE="$(read_state_field "config_file")"
DATA_DIR="$(read_state_field "data_dir")"

if [[ -z "${METHOD}" ]]; then
  echo "Invalid Loki install state file: ${STATE_FILE}"
  exit 1
fi

remove_data=false
read -r -p "Remove Loki data dir and config files? [y/N]: " confirm
case "${confirm}" in
  y|Y|yes|YES) remove_data=true ;;
  *) remove_data=false ;;
esac

case "${METHOD}" in
  brew)
    if command -v brew >/dev/null 2>&1; then
      brew services stop grafana/loki/loki >/dev/null 2>&1 || brew services stop loki >/dev/null 2>&1 || true
      brew uninstall grafana/loki/loki >/dev/null 2>&1 || brew uninstall loki >/dev/null 2>&1 || true
    else
      echo "Homebrew not found. Please uninstall Loki manually."
    fi
    ;;
  apt)
    if command -v systemctl >/dev/null 2>&1; then
      sudo systemctl stop loki >/dev/null 2>&1 || true
      sudo systemctl disable loki >/dev/null 2>&1 || true
    fi
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get remove -y loki >/dev/null 2>&1 || true
    else
      echo "apt-get not found. Please uninstall Loki manually."
    fi
    ;;
  docker)
    if command -v docker >/dev/null 2>&1; then
      docker rm -f loki >/dev/null 2>&1 || true
    else
      echo "Docker not found. Please remove the Loki container manually."
    fi
    ;;
  *)
    echo "Unknown install method '${METHOD}'."
    ;;
esac

if [[ "${remove_data}" == "true" ]]; then
  if [[ -n "${CONFIG_FILE}" && -f "${CONFIG_FILE}" ]]; then
    rm -f "${CONFIG_FILE}"
  fi
  if [[ -n "${DATA_DIR}" && -d "${DATA_DIR}" ]]; then
    rm -rf "${DATA_DIR}"
  fi
  if [[ "${METHOD}" == "apt" ]]; then
    if [[ -d /etc/loki ]]; then
      sudo rm -rf /etc/loki
    fi
  fi
fi

rm -f "${STATE_FILE}"
echo "Loki uninstall complete."
