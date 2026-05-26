import requests
import time
import json
import os
import sys
from pathlib import Path

# Configuration
PORTAL_URL = "http://127.0.0.1:5001"
# Admin credentials we just fixed
USERNAME = "admin"
PASSWORD = "admin1234"

def run_test_verification():
    print(f"--- Starting Test Verification for {USERNAME} ---")
    
    session = requests.Session()
    
    # 1. Login
    print("Logging in...")
    login_resp = session.post(f"{PORTAL_URL}/login", data={
        "username": USERNAME,
        "password": PASSWORD
    }, allow_redirects=True)
    
    if "Welcome back" not in login_resp.text and login_resp.status_code != 200:
        print("Login failed!")
        return

    # 2. Start Verification Run
    print("Submitting verification run (SPIN tool)...")
    contract_code = """
/* Simple Vault Contract */
byte state = 0; // 0: Idle, 1: Deposited, 2: Locked
bool lock = false;
int amount = 0;
int user_collateral = 1000;
int user_debt = 0;
int health_factor = 200;

proctype Vault() {
    do
    :: state == 0 -> 
       atomic { amount = 500; state = 1; }
    :: state == 1 ->
       atomic { lock = true; state = 2; }
    :: state == 2 ->
       atomic { lock = false; state = 0; amount = 0; }
    od
}

init {
    run Vault();
}

ltl safety_no_overflow { [] (amount >= 0 && amount <= 1000000) }
ltl safety_reentrancy { [] !(lock && amount > 100) }
"""
    
    # We use /api/v1/run which is what the frontend uses
    # It takes tools[] as an array, but we'll send it as a list
    run_data = {
        "tools": ["SPIN"],
        "code": contract_code,
        "filename": "TestVault.pml",
        "spec_text": ""
    }
    
    # Note: /api/v1/run expects tools as a list in JSON or multiple 'tools' keys in form
    # The frontend uses FormData.
    files = {
        "code": (None, contract_code),
        "filename": (None, "TestVault.pml"),
        "tools": (None, "SPIN")
    }
    
    # Actually the /api/v1/run handler in api_v1.py likely handles 'tool' or 'tools'
    # Let's try the direct run endpoint
    run_resp = session.post(f"{PORTAL_URL}/api/v1/run", data={
        "tool": "SPIN",
        "code": contract_code,
        "filename": "TestVault.pml",
        "verif_url": "http://127.0.0.1:9006"
    })
    
    if not run_resp.ok:
        print(f"Failed to start run: {run_resp.text}")
        return
        
    data = run_resp.json()
    job_id = data.get("job_id")
    audit_id = data.get("audit_id")
    print(f"Run accepted. Job ID: {job_id}, Audit ID: {audit_id}")

    # 3. Poll for Progress
    print("Polling for progress...")
    for _ in range(10):
        # Check Job Status
        job_resp = session.get(f"{PORTAL_URL}/api/v1/job/{job_id}")
        if job_resp.ok:
            job_status = job_resp.json()
            status = job_status.get("status")
            print(f"Job Status: {status}")
            if status in ("completed", "failed", "error"):
                break
        
        # Check Dashboard Summary/State for progress
        state_resp = session.get(f"{PORTAL_URL}/api/v1/state/current")
        if state_resp.ok:
            state = state_resp.json()
            spin_state = state.get("spin", {})
            prog = spin_state.get("progress", 0)
            print(f"Current Progress: {prog}%")
            
        time.sleep(2)

    print("--- Test Verification Complete ---")
    print(f"Preview URL for active progress: {PORTAL_URL}/active")

if __name__ == "__main__":
    run_test_verification()
