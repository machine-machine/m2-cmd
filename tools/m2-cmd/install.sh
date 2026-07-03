#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
AGENT_SCRIPT="${REPO_ROOT}/scripts/m2-agent.py"

if [[ ! -f "${AGENT_SCRIPT}" ]]; then
  echo "m2-agent.py not found at ${AGENT_SCRIPT}" >&2
  exit 1
fi

DEFAULT_BIN_PATH="${M2_BIN_PATH:-${HOME}/.local/bin/m2}"
BIN_PATH="${DEFAULT_BIN_PATH}"
FORWARD_ARGS=()

show_help() {
  cat <<'EOF'
Usage:
  install.sh [options] [m2-agent args]

Options:
  --bin PATH           Target path for m2 executable (default: ~/.local/bin/m2)
  -h, --help           Show this help and exit

Any additional arguments are passed through to m2-agent.py.
Useful examples:
  --backend-url http://192.168.31.99:4000/v1/chat/completions
  --model ornith-coding
  --api-key sk-...
  --timeout 60
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
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

mkdir -p "$(dirname "${BIN_PATH}")"

python3 "${AGENT_SCRIPT}" --install --bin "${BIN_PATH}" "${FORWARD_ARGS[@]}"

if ! command -v m2 >/dev/null; then
  BIN_DIR="$(dirname "${BIN_PATH}")"
  echo "Path hint: export PATH=\"${BIN_DIR}:$PATH\""
fi

echo "Installed m2 command at ${BIN_PATH}"
