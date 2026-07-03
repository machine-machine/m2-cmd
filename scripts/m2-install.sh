#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="${SCRIPT_DIR}/../tools/m2-cmd"

if [[ -f "${TOOL_DIR}/install.sh" ]]; then
  bash "${TOOL_DIR}/install.sh" "$@"
else
  # Fallback for older layouts
  python3 "${SCRIPT_DIR}/m2-agent.py" --install "$@"
fi
