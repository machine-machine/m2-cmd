#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]-}" && "${BASH_SOURCE[0]}" != "bash" && "${BASH_SOURCE[0]}" != "sh" && "${BASH_SOURCE[0]}" != "-" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  SCRIPT_DIR="${PWD}"
fi
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
AGENT_SCRIPT="${REPO_ROOT}/scripts/m2-agent.py"

if [[ ! -f "${AGENT_SCRIPT}" ]]; then
  echo "m2-agent.py not found at ${AGENT_SCRIPT}" >&2
  exit 1
fi

DEFAULT_BIN_PATH="${M2_BIN_PATH:-${HOME}/.local/bin/m2}"
BIN_PATH="${DEFAULT_BIN_PATH}"
FORWARD_ARGS=()
ADD_PATH=0

show_help() {
  cat <<'EOF'
Usage:
  install.sh [options] [m2-agent args]

Options:
  --bin PATH           Target path for m2 executable (default: ~/.local/bin/m2)
  --add-path           Add BIN_PATH directory to shell profile for future shells
  -h, --help           Show this help and exit

Any additional arguments are passed through to m2-agent.py.
Useful examples:
  --backend-url http://192.168.31.99:4000/v1/chat/completions
  --model ornith-coding
  --api-key sk-...
  --timeout 60
EOF
}

check_and_print_path() {
  local bin_dir="$1"

  if ! command -v m2 >/dev/null; then
    echo "Path check: '$bin_dir' is not on your current PATH"
    echo "One-shot for current shell: export PATH=\"${bin_dir}:$PATH\""

    if [[ ${ADD_PATH} -eq 1 ]]; then
      local shell_name
      shell_name="${SHELL##*/}"
      local profile=""
      local line=''
      case "${shell_name}" in
        zsh)
          profile="${HOME}/.zshrc"
          ;;
        bash)
          profile="${HOME}/.bashrc"
          ;;
        fish)
          profile="${HOME}/.config/fish/config.fish"
          ;;
        *)
          profile="${HOME}/.profile"
          ;;
      esac

      mkdir -p "$(dirname "${profile}")"
      if [[ ! -f "${profile}" ]]; then
        : > "${profile}"
      fi

      if [[ "${shell_name}" == fish ]]; then
        line="set -gx PATH ${bin_dir} \$PATH"
      else
        line="export PATH=\"${bin_dir}:\$PATH\" # added by m2-cmd installer"
      fi

      if grep -Fqx "${line}" "${profile}"; then
        echo "Path already present in ${profile}"
      else
        echo "${line}" >> "${profile}"
        echo "Added PATH entry to ${profile}"
      fi

      export PATH="${bin_dir}:$PATH"
      echo "Also added to current shell for this installer invocation"
    else
      echo "If you want this persisted, rerun with --add-path or run the export command above."
    fi
  else
    echo "PATH check: ok (m2 is discoverable)"
  fi
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
    --add-path)
      ADD_PATH=1
      shift
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

# Bash 3.2 on macOS treats an empty array expansion as unbound under
# `set -u` in some contexts, even when the array was initialized with `=()`.
# Branch before expanding FORWARD_ARGS so the piped one-command installer works
# when the user passes only installer flags such as --add-path.
if [[ ${#FORWARD_ARGS[@]} -gt 0 ]]; then
  python3 "${AGENT_SCRIPT}" --install --bin "${BIN_PATH}" "${FORWARD_ARGS[@]}"
else
  python3 "${AGENT_SCRIPT}" --install --bin "${BIN_PATH}"
fi

BIN_DIR="$(dirname "${BIN_PATH}")"
check_and_print_path "${BIN_DIR}"

echo "Installed m2 command at ${BIN_PATH}"
