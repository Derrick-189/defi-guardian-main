import os
import json
from datetime import datetime

# Mock data for testing
mock_state = {
    "spin": {
        "status": "PASS",
        "timestamp": datetime.now().isoformat(),
        "success": True
    },
    "kani": {
        "status": "FAIL",
        "timestamp": datetime.now().isoformat(),
        "success": False
    }
}

with open("verification_state.json", "w") as f:
    json.dump(mock_state, f)

# Import and run report generator
from app import export_verification_report

report_path, error = export_verification_report()
if report_path:
    print(f"Report generated successfully at: {report_path}")
    if os.path.exists(report_path):
        print("File exists on disk.")
else:
    print(f"Failed to generate report: {error}")
