import sys
import os
from pathlib import Path

# Add project root and web_portal to path
PROJECT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "web_portal"))

try:
    from web_portal.app import app
    print("App imported successfully!")
except Exception as e:
    import traceback
    print(f"Error importing app: {e}")
    traceback.print_exc()
    sys.exit(1)
