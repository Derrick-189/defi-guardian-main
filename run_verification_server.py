#!/usr/bin/env python3
"""
DeFi Guardian — Verification Server Runner
Starts the verification server that exposes the desktop verification engine as HTTP API.
"""

import os
import sys
from pathlib import Path

# Add web_portal to path
PORTAL_DIR = Path(__file__).parent / "web_portal"
sys.path.insert(0, str(PORTAL_DIR))

def main():
    print("Starting DeFi Guardian Verification Server...")
    print("This server exposes real verification tools as HTTP API.")
    print("Make sure verification tools (spin, verus, etc.) are installed.")
    print()

    # Import and run the server
    from verification_server import app

    port = int(os.getenv("VERIFICATION_PORT", "9000"))
    print(f"Server will run on http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    print()

    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()