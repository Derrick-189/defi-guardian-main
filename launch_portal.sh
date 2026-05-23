#!/usr/bin/env bash
# DeFi Guardian — Launch Web Portal
# Usage: ./launch_portal.sh [port]
set -e

PORT=${1:-5000}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Kill anything already on the port
EXISTING=$(ss -tlnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | head -1)
if [ -n "$EXISTING" ]; then
  echo "Stopping existing process on port ${PORT} (pid ${EXISTING})…"
  kill "$EXISTING" 2>/dev/null || true
  sleep 1
fi

echo "╔══════════════════════════════════════════════════════╗"
echo "║          DeFi Guardian Web Portal v2.0              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "  URL   : http://localhost:${PORT}"
echo "  Login : demo / demo1234"
echo "  Ctrl+C to stop"
echo ""

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/web_portal"

# Prefer project virtualenv Python if present
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
  PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python3"
else
  PYTHON_EXEC="python3"
fi

"$PYTHON_EXEC" -c "
import eventlet
eventlet.monkey_patch()
import sys, os
from pathlib import Path
SCRIPT_DIR = os.getcwd()
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, 'web_portal'))
from web_portal.app import app, socketio
socketio.run(app, port=${PORT}, use_reloader=False, allow_unsafe_werkzeug=True)
"
