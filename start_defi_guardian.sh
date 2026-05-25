#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  DeFi Guardian — Master Startup Script
#  Opens all 5 components in separate terminal tabs IN ORDER
#  Usage: chmod +x start_defi_guardian.sh && ./start_defi_guardian.sh
# ═══════════════════════════════════════════════════════════════

PROJECT_DIR="$HOME/defi-guardian-main"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
fail() { echo -e "${RED}✘ $*${NC}"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          DeFi Guardian — Starting All Services          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Pre-flight checks ───────────────────────────────────────────
[ ! -d "$PROJECT_DIR" ] && fail "Project not found at $PROJECT_DIR"
[ ! -f "$VENV_PYTHON" ] && fail "Venv not found — run: cd $PROJECT_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

if [ -f "$ENV_FILE" ]; then
  source "$ENV_FILE"
  ok "Loaded .env"
else
  warn ".env not found — using system environment"
fi

# ── Check cloudflared ───────────────────────────────────────────
CLOUDFLARED_CMD=""
if command -v cloudflared &>/dev/null; then
  CLOUDFLARED_CMD="cloudflared"
elif [ -f "$PROJECT_DIR/cloudflared" ]; then
  CLOUDFLARED_CMD="$PROJECT_DIR/cloudflared"
else
  warn "cloudflared not found — tunnel will be SKIPPED"
fi

# ── Detect terminal emulator ────────────────────────────────────
open_tab() {
  local TITLE="$1"; local CMD="$2"
  if command -v gnome-terminal &>/dev/null; then
    gnome-terminal --tab --title="$TITLE" -- bash -c "$CMD; exec bash"
  elif command -v xterm &>/dev/null; then
    xterm -title "$TITLE" -e bash -c "$CMD; exec bash" &
  elif command -v konsole &>/dev/null; then
    konsole --new-tab -e bash -c "$CMD; exec bash" &
  else
    fail "No terminal found. Use start_manual.sh instead."
  fi
}

# ═══════════════════════════════════════════════════════════════
# TERMINAL 1 — Verification Server (the engine with real tools)
# ═══════════════════════════════════════════════════════════════
ok "Terminal 1 — Verification Server (port 9000)..."
open_tab "1 - Verification Server" "
  echo '══════════════════════════════════════════════════';
  echo '  [1/5] Verification Server — port 9000          ';
  echo '══════════════════════════════════════════════════';
  cd $PROJECT_DIR
  source $ENV_FILE 2>/dev/null || true
  export VSERVER_TOKEN=\${VSERVER_TOKEN:-formal-verification-token}
  export PYTHONPATH=$PROJECT_DIR:$PROJECT_DIR/web_portal
  $VENV_PYTHON web_portal/verification_server.py --port 9000
"
sleep 3

# ═══════════════════════════════════════════════════════════════
# TERMINAL 2 — Verification Worker (picks jobs from the queue)
# ═══════════════════════════════════════════════════════════════
ok "Terminal 2 — Verification Worker..."
open_tab "2 - Verification Worker" "
  echo '══════════════════════════════════════════════════';
  echo '  [2/5] Verification Worker — queue processor    ';
  echo '  Polls for pending jobs and runs them via the   ';
  echo '  verification server. REQUIRED for results.     ';
  echo '══════════════════════════════════════════════════';
  cd $PROJECT_DIR
  source $ENV_FILE 2>/dev/null || true
  export VSERVER_TOKEN=\${VSERVER_TOKEN:-formal-verification-token}
  export PYTHONPATH=$PROJECT_DIR:$PROJECT_DIR/web_portal
  $VENV_PYTHON verification_worker.py
"
sleep 2

# ═══════════════════════════════════════════════════════════════
# TERMINAL 3 — Cloudflare Tunnel (exposes verifier to internet)
# ═══════════════════════════════════════════════════════════════
if [ -n "$CLOUDFLARED_CMD" ]; then
  ok "Terminal 3 — Cloudflare Tunnel..."
  open_tab "3 - Cloudflare Tunnel" "
    echo '══════════════════════════════════════════════════';
    echo '  [3/5] Cloudflare Tunnel                        ';
    echo '  Copy the https://xxxx.trycloudflare.com URL    ';
    echo '  and set it as VSERVER_URL on Render.           ';
    echo '══════════════════════════════════════════════════';
    $CLOUDFLARED_CMD tunnel --url http://localhost:9000
  "
  sleep 5
else
  warn "Terminal 3 — SKIPPED (cloudflared not installed)"
fi

# ═══════════════════════════════════════════════════════════════
# TERMINAL 4 — Web Portal (localhost:5001)
# ═══════════════════════════════════════════════════════════════
ok "Terminal 4 — Web Portal (port 5001)..."
open_tab "4 - Web Portal" "
  echo '══════════════════════════════════════════════════';
  echo '  [4/5] Web Portal — http://localhost:5001       ';
  echo '  Login: demo / demo1234                         ';
  echo '══════════════════════════════════════════════════';
  cd $PROJECT_DIR
  source $ENV_FILE 2>/dev/null || true
  export VSERVER_TOKEN=\${VSERVER_TOKEN:-formal-verification-token}
  export VSERVER_URL=\${VSERVER_URL:-http://127.0.0.1:9000}
  export PYTHONPATH=$PROJECT_DIR:$PROJECT_DIR/web_portal
  export PORT=5001
  export FLASK_ENV=dev
  cd web_portal
  ../$VENV_PYTHON app.py
"
sleep 4

# ═══════════════════════════════════════════════════════════════
# TERMINAL 5 — Health Check
# ═══════════════════════════════════════════════════════════════
ok "Terminal 5 — Health Check..."
open_tab "5 - Health Check" "
  echo '══════════════════════════════════════════════════';
  echo '  [5/5] Health Check                             ';
  echo '══════════════════════════════════════════════════';
  sleep 4
  echo ''

  VS=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9000/health 2>/dev/null)
  [ \"\$VS\" = '200' ] && echo '✔ Verification server   OK  (port 9000)' || echo '✘ Verification server   FAILED'

  WP=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5001/ 2>/dev/null)
  [ \"\$WP\" = '200' ] && echo '✔ Web portal            OK  (port 5001)' || echo '✘ Web portal            FAILED'

  # Check worker is alive (it writes to queue DB)
  QUEUEDB=$PROJECT_DIR/web_portal/verification_queue.db
  if [ -f \"\$QUEUEDB\" ]; then
    echo '✔ Verification worker   OK  (queue DB exists)'
  else
    echo '⚠ Verification worker   queue DB not yet created (normal if no job run yet)'
  fi

  cd $PROJECT_DIR
  source $ENV_FILE 2>/dev/null || true
  $VENV_PYTHON -c \"
import os, psycopg2
url = os.environ.get('DATABASE_URL','')
if not url:
    print('✘ DATABASE_URL not set')
else:
    try:
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM users')
        n = cur.fetchone()[0]
        conn.close()
        print(f'✔ PostgreSQL database   OK  ({n} users)')
    except Exception as e:
        print(f'✘ PostgreSQL            FAILED: {e}')
\"
  echo ''
  echo '──────────────────────────────────────────────────'
  echo '  Local portal  : http://localhost:5001'
  echo '  Render portal : https://defi-guardian-main.onrender.com'
  echo '  Login         : demo / demo1234'
  echo '──────────────────────────────────────────────────'
  read -p 'Press Enter to close...'
"

echo ""
ok "All services launched."
echo ""
echo "  Local portal  : http://localhost:5001"
echo "  Render portal : https://defi-guardian-main.onrender.com"
echo "  Login         : demo / demo1234"
echo ""
