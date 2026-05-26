import json
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
VERIFICATION_STATE = PROJECT_DIR / "verification_state.json"

def reset_state():
    TOOLS = ["spin", "coq", "lean", "certora", "kani", "prusti", "creusot", "verus"]
    state = {}
    for t in TOOLS:
        state[t] = {
            "status": "Not run",
            "progress": 0,
            "success": None,
            "timestamp": "",
            "model_name": ""
        }
    state["active_tool"] = "SPIN"
    state["active_status"] = "IDLE"
    state["success"] = None
    state["ltl_results"] = []
    
    with open(VERIFICATION_STATE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"Successfully reset {VERIFICATION_STATE}")

if __name__ == "__main__":
    reset_state()
