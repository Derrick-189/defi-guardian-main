import requests
import sqlite3
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
# Set your remote portal URL here (e.g., 'https://defi-guardian-main.onrender.com')
REMOTE_URL = os.environ.get("REMOTE_PORTAL_URL", "https://defi-guardian-main.onrender.com")
# Set the secret sync token (should match the one on the server)
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "my_secret_123")

PROJECT_DIR = Path(__file__).parent.resolve()
LOCAL_DB_PATH = PROJECT_DIR / "web_portal" / "defi_guardian.db"

def sync_local_to_remote():
    """
    Push local verification runs and users to the remote PostgreSQL instance
    via the portal's Sync API.
    """
    if not LOCAL_DB_PATH.exists():
        print(f"Local database not found at {LOCAL_DB_PATH}")
        return

    print(f"Connecting to local database: {LOCAL_DB_PATH}")
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Fetch local audits and users
    print("Fetching local records...")
    audits = cursor.execute("SELECT * FROM audit_history ORDER BY audit_date DESC LIMIT 50").fetchall()
    users = cursor.execute("SELECT * FROM user WHERE username != 'demo'").fetchall()
    
    sync_jobs = []
    for row in audits:
        sync_jobs.append(dict(row))

    sync_users = []
    for row in users:
        sync_users.append(dict(row))

    if not sync_jobs and not sync_users:
        print("No local data to sync.")
        return

    # 2. Push to remote API
    print(f"Pushing {len(sync_jobs)} jobs and {len(sync_users)} users to {REMOTE_URL}...")
    try:
        endpoint = f"{REMOTE_URL.rstrip('/')}/api/v1/sync-audit"
        headers = {
            "Content-Type": "application/json",
            "X-Sync-Token": SYNC_TOKEN
        }
        
        payload = {
            "jobs": [
                {
                    "file": a['filename'],
                    "tool": a['tool_used'],
                    "status": a['status'],
                    "audit_date": a['audit_date'],
                    "details": {
                        "states": a.get('states_explored', 0),
                        "transitions": a.get('transitions', 0),
                        "depth": a.get('depth_reached', 0)
                    },
                    "specs": a.get('ltl_properties', ""),
                    "log_content": a.get('verification_output', ""),
                    "trail_path": a.get('report_path', "")
                }
                for a in sync_jobs
            ],
            "users": [
                {
                    "username": u['username'],
                    "email": u.get('email'),
                    "password_hash": u.get('password_hash'),
                    "role": u.get('role', 'user'),
                    "organization": u.get('organization')
                }
                for u in sync_users
            ]
        }

        response = requests.post(endpoint, json=payload, headers=headers, timeout=60)
        
        if response.ok:
            try:
                print(f"Successfully synced data! Server response: {response.json().get('status')}")
            except Exception:
                print(f"Successfully synced data, but server returned non-JSON: {response.text[:200]}")
        else:
            if response.status_code == 302 or "login" in response.text.lower():
                print("Sync failed: Authentication required. Check if SYNC_TOKEN is set correctly on both local and Render.")
            else:
                print(f"Sync failed with status {response.status_code}: {response.text[:200]}")

    except Exception as e:
        print(f"An error occurred during sync: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        REMOTE_URL = sys.argv[1]
    
    print(f"Starting sync to {REMOTE_URL}...")
    sync_local_to_remote()
