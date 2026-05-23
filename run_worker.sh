#!/usr/bin/env bash
# Run verification worker with project virtualenv python when available
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
  PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python3"
else
  PYTHON_EXEC="python3"
fi

# Ensure PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/web_portal"

exec "$PYTHON_EXEC" verification_worker.py
