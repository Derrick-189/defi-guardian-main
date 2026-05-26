import requests
import time

PORTAL_URL = "http://127.0.0.1:5001"
USERNAME = "admin"
PASSWORD = "admin1234"

def trigger_benchmarks():
    session = requests.Session()
    
    # 1. Login
    print("Logging in...")
    login_resp = session.post(f"{PORTAL_URL}/login", data={
        "username": USERNAME,
        "password": PASSWORD
    }, allow_redirects=True)
    
    if login_resp.status_code != 200:
        print("Login failed!")
        return

    # 2. Trigger Benchmarks
    print("Triggering benchmarks...")
    resp = session.post(f"{PORTAL_URL}/api/v1/benchmarks/run")
    print(f"Status: {resp.status_code}, Body: {resp.json()}")

if __name__ == "__main__":
    trigger_benchmarks()
