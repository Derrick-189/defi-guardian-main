import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

from web_portal.app import app

def test_routes():
    print("Testing routes...")
    with app.test_client() as client:
        # Test API v1 endpoint
        resp = client.get('/api/v1/state/current')
        print(f"GET /api/v1/state/current: {resp.status_code}")
        
        # Test redirect from old API
        resp = client.get('/api/state/current')
        print(f"GET /api/state/current (redirect): {resp.status_code} -> {resp.location}")
        
        # Test a public route
        resp = client.get('/')
        print(f"GET /: {resp.status_code}")

if __name__ == "__main__":
    test_routes()
