#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  DeFi Guardian — Manual Commands Reference
#  Open 5 terminal tabs and paste each block IN ORDER
# ═══════════════════════════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         DeFi Guardian — 5-Terminal Setup Guide          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Open 5 terminal tabs and paste each block IN ORDER."
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " TERMINAL 1 — Verification Server (the tool engine)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'T1'

cd ~/defi-guardian-main
source .env
export VSERVER_TOKEN=formal-verification-token
export PYTHONPATH=~/defi-guardian-main:~/defi-guardian-main/web_portal
./.venv/bin/python web_portal/verification_server.py --port 9000

T1

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " TERMINAL 2 — Verification Worker (REQUIRED — processes jobs)"
echo " Without this, all verification runs stay PENDING forever!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'T2'

cd ~/defi-guardian-main
source .env
export VSERVER_TOKEN=formal-verification-token
export PYTHONPATH=~/defi-guardian-main:~/defi-guardian-main/web_portal
./.venv/bin/python verification_worker.py

T2

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " TERMINAL 3 — Cloudflare Tunnel (exposes verifier to internet)"
echo " Copy the https://xxxx.trycloudflare.com URL it prints"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'T3'

# If installed via package:
cloudflared tunnel --url http://localhost:9000

# If installed as local binary in project folder:
~/defi-guardian-main/cloudflared tunnel --url http://localhost:9000

T3

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " TERMINAL 4 — Web Portal (replace TUNNEL_URL with Terminal 3 URL)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'T4'

cd ~/defi-guardian-main
source .env
export VSERVER_TOKEN=formal-verification-token
export VSERVER_URL=https://REPLACE-WITH-YOUR-TUNNEL-URL.trycloudflare.com
export PYTHONPATH=~/defi-guardian-main:~/defi-guardian-main/web_portal
export PORT=5001
export FLASK_ENV=dev
cd web_portal
../.venv/bin/python app.py

T4

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " TERMINAL 5 — Sanity Check (run after all others are up)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'T5'

cd ~/defi-guardian-main
source .env

# 1. Verification server
curl -s http://127.0.0.1:9000/health && echo "✔ Verification server OK" || echo "✘ Verification server FAILED"

# 2. Web portal
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5001/ | grep -q 200 \
  && echo "✔ Web portal OK" || echo "✘ Web portal FAILED"

# 3. Worker (check queue DB was created)
[ -f ~/defi-guardian-main/web_portal/verification_queue.db ] \
  && echo "✔ Worker queue DB exists" \
  || echo "⚠ Worker queue DB not yet created (submit a job first)"

# 4. Database
./.venv/bin/python -c "
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
        print(f'✔ PostgreSQL OK — {n} users')
    except Exception as e:
        print(f'✘ PostgreSQL FAILED: {e}')
"

T5

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " HOW THE 5 PARTS CONNECT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Web Portal (T4)"
echo "       ↓ user clicks Verify → job written to queue DB"
echo "  Verification Worker (T2)  ← polls queue DB every 1 second"
echo "       ↓ picks up job → calls verification server"
echo "  Verification Server (T1)  ← runs SPIN / Kani / Prusti etc."
echo "       ↓ result returned → worker saves to PostgreSQL"
echo "  Cloudflare Tunnel (T3)    ← makes T1 reachable from Render"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " AFTER GETTING TUNNEL URL — set on Render environment vars:"
echo "   VSERVER_URL   = https://xxxx.trycloudflare.com"
echo "   VSERVER_TOKEN = formal-verification-token"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Local portal  : http://localhost:5001"
echo "  Render portal : https://defi-guardian-main.onrender.com"
echo "  Login         : demo / demo1234"
echo ""
