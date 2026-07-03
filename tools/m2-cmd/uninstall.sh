#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CONFIG_DIR="${M2_CONFIG_DIR:-${HOME}/.config/m2-agent}"
CONFIG_FILE="${CONFIG_DIR}/config.json"
CONTEXT_FILE="${CONFIG_DIR}/baseline-context.json"

DEFAULT_BIN_PATH="${M2_BIN_PATH:-${HOME}/.local/bin/m2}"
BIN_PATH="${DEFAULT_BIN_PATH}"
ASSUME_YES=0
KEEP_STATE=0

show_help() {
  cat <<'EOF'
Usage:
  uninstall.sh [options]

Options:
  --bin PATH        Path to m2 executable to remove (default: ~/.local/bin/m2)
  --keep-state      Keep config and baseline-context files
  --yes, -y         Delete without confirmation
  -h, --help        Show this help and exit

This removes the installed m2 wrapper and (unless --keep-state is set)
removes:
  ~/.config/m2-agent/config.json
  ~/.config/m2-agent/baseline-context.json
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bin)
      if [[ $# -lt 2 ]]; then
        echo "--bin requires a path" >&2
        show_help
        exit 1
      fi
      BIN_PATH="$2"
      shift 2
      ;;
    --keep-state)
      KEEP_STATE=1
      shift
      ;;
    --yes|-y)
      ASSUME_YES=1
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      show_help
      exit 1
      ;;
  esac
done

if [[ ! -e "${BIN_PATH}" && ! -f "${CONFIG_FILE}" && ! -f "${CONTEXT_FILE}" ]]; then
  echo "m2 command not found and no state found; nothing to remove"
  exit 0
fi

if [[ ${ASSUME_YES} -ne 1 ]]; then
  echo "Will remove:"
  [[ -f "${BIN_PATH}" ]] && echo "  - ${BIN_PATH}"
  [[ -f "${CONFIG_FILE}" ]] && echo "  - ${CONFIG_FILE}"
  [[ -f "${CONTEXT_FILE}" ]] && echo "  - ${CONTEXT_FILE}"
  if [[ ${KEEP_STATE} -eq 1 ]]; then
    echo "  - keeping state files (per --keep-state)"
  else
    echo "  - ${CONFIG_DIR}/* (state files)"
  fi

  read -r -p "Proceed with uninstall? [y/N] " ANSWER
  if [[ "${ANSWER}" != [yY] ]]; then
    echo "Uninstall canceled"
    exit 1
  fi
fi

if [[ -f "${BIN_PATH}" ]]; then
  rm -f "${BIN_PATH}"
  echo "Removed ${BIN_PATH}"
fi

if [[ ${KEEP_STATE} -eq 0 ]]; then
  if [[ -f "${CONFIG_FILE}" ]]; then
    rm -f "${CONFIG_FILE}"
    echo "Removed ${CONFIG_FILE}"
  fi

  if [[ -f "${CONTEXT_FILE}" ]]; then
    rm -f "${CONTEXT_FILE}"
    echo "Removed ${CONTEXT_FILE}"
  fi

  if [[ -d "${CONFIG_DIR}" && -z "$(ls -A "${CONFIG_DIR}")" ]]; then
    rmdir "${CONFIG_DIR}"
    echo "Removed ${CONFIG_DIR}"
  fi
fi

echo "Uninstall complete"
