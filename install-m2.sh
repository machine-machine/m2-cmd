#!/usr/bin/env bash
set -euo pipefail

resolve_script_dir() {
  local script_path="${1-}"
  if [[ -z "${script_path}" || "${script_path}" == "-" || "${script_path}" == "bash" || "${script_path}" == "sh" ]]; then
    echo "${PWD}"
    return 0
  fi

  cd "$(dirname "${script_path}")" && pwd
}

SCRIPT_DIR="$(resolve_script_dir "${BASH_SOURCE[0]-}")"
LOCAL_INSTALL="${SCRIPT_DIR}/tools/m2-cmd/install.sh"

if [[ -f "${LOCAL_INSTALL}" ]]; then
  bash "${LOCAL_INSTALL}" "$@"
  exit 0
fi

download_file() {
  local source_url="$1"
  local target_path="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${source_url}" -o "${target_path}"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "${target_path}" "${source_url}"
  else
    echo "No downloader found (install curl or wget)" >&2
    return 1
  fi
}

REMOTE_BASE_URL="${M2_CMD_REMOTE_BASE_URL:-https://github.com/machine-machine/m2-cmd/raw/refs/heads/main}"
REMOTE_INSTALL_DIR="${M2_CMD_REMOTE_INSTALL_DIR:-${HOME}/.local/share/m2-cmd}"
INSTALL_URL="${REMOTE_BASE_URL}/tools/m2-cmd/install.sh"
AGENT_URL="${REMOTE_BASE_URL}/scripts/m2-agent.py"

mkdir -p "${REMOTE_INSTALL_DIR}/tools/m2-cmd" "${REMOTE_INSTALL_DIR}/scripts"

download_file "${INSTALL_URL}" "${REMOTE_INSTALL_DIR}/tools/m2-cmd/install.sh"
download_file "${AGENT_URL}" "${REMOTE_INSTALL_DIR}/scripts/m2-agent.py"

bash "${REMOTE_INSTALL_DIR}/tools/m2-cmd/install.sh" "$@"
