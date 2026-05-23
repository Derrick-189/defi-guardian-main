#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${PROJECT_DIR}/.prusti.env" ]; then
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.prusti.env"
else
  echo "WARN: ${PROJECT_DIR}/.prusti.env not found."
  echo "      Run ./setup_prusti_defi_guardian.sh first."
fi

exec python3 "${PROJECT_DIR}/desktop_app.py"
