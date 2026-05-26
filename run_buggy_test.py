import requests
import time
import json

# Configuration
PORTAL_URL = "http://127.0.0.1:5001"
USERNAME = "admin"
PASSWORD = "admin1234"

def run_buggy_verification():
    print("--- Starting Buggy Verification Test ---")
    session = requests.Session()
    
    # 1. Login
    print("Logging in...")
    session.post(f"{PORTAL_URL}/login", data={"username": USERNAME, "password": PASSWORD})

    # 2. Submit BUGGY contract (Reentrancy vulnerability)
    print("Submitting buggy contract (VulnerableVault.pml)...")
    buggy_code = """
/* Vulnerable Vault Contract with Reentrancy */
int balance = 1000;
bool lock = false;
int user_withdraw_amount = 0;

proctype User() {
    do
    :: balance > 100 ->
       // Simulate a withdrawal that doesn't check lock properly
       atomic {
           user_withdraw_amount = 100;
           balance = balance - 100;
       }
    od
}

// LTL to catch reentrancy: lock should always be true during critical sections
// In this buggy version, we intentionally omit the lock check
ltl safety_reentrancy { [] !(balance < 0) }
"""
    
    # We force a "FAIL" by using the simulator's error injection or just buggy LTL
    # The verification_server.py usually runs real SPIN if available, or we use simulated tool
    run_resp = session.post(f"{PORTAL_URL}/api/v1/run", data={
        "tool": "SPIN",
        "code": buggy_code,
        "filename": "VulnerableVault.pml",
        "verif_url": "http://127.0.0.1:9000" # Real verification server port
    })
    
    if not run_resp.ok:
        print(f"Failed: {run_resp.text}")
        return
        
    data = run_resp.json()
    job_id = data.get("job_id")
    print(f"Job started: {job_id}")

    # 3. Wait for completion
    print("Waiting for failure trace...")
    for _ in range(10):
        resp = session.get(f"{PORTAL_URL}/api/v1/job/{job_id}")
        if resp.ok:
            status = resp.json().get("status")
            print(f"Status: {status}")
            if status in ("failed", "error", "FAIL"):
                break
        time.sleep(2)

    print(f"--- Buggy Test Complete ---")
    print(f"Preview the failure results here: {PORTAL_URL}/counterexample/latest")

if __name__ == "__main__":
    run_buggy_verification()
