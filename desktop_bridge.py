"""
DeFi Guardian — Desktop Bridge
Helper used by desktop_app.py to POST VerificationCompleteEvent to the web portal.
Import and call notify_portal() after each verification run.
"""
from __future__ import annotations
import json, os, threading, time
from datetime import datetime
from pathlib import Path
from typing import Optional

PORTAL_URL = os.environ.get("DG_PORTAL_URL", "http://localhost:5001")
PROJECT_DIR = Path(__file__).parent
VERIFICATION_STATE = PROJECT_DIR / "verification_state.json"
AUDIT_LOG = PROJECT_DIR / "generated" / "reports" / "audit_log.json"


def notify_portal(
    tool: str,
    filename: str,
    status: str,
    audit_id: str = "",
    ltl_results: list | None = None,
    states: int = 0,
    transitions: int = 0,
    depth: int = 0,
    message: str = "",
) -> bool:
    """
    POST a VerificationCompleteEvent to the portal's /api/events/emit endpoint.
    Non-blocking — runs in a daemon thread.
    Returns True if the request was dispatched (not necessarily successful).
    """
    payload = {
        "audit_id":    audit_id or _short_id(),
        "tool":        tool.upper(),
        "filename":    filename,
        "timestamp":   datetime.now().isoformat(),
        "status":      status.upper(),
        "ltl_results": ltl_results or [],
        "states":      states,
        "transitions": transitions,
        "depth":       depth,
        "message":     message,
    }

    def _post():
        try:
            import urllib.request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{PORTAL_URL}/api/events/emit",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass  # Portal may not be running — that's fine

    t = threading.Thread(target=_post, daemon=True)
    t.start()
    return True


def save_verification_state(state: dict) -> None:
    """Write verification_state.json (triggers portal file-watcher)."""
    try:
        VERIFICATION_STATE.write_text(
            json.dumps(state, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[bridge] Could not write verification_state.json: {e}")


def append_audit_log(entry: dict) -> None:
    """Append a run record to audit_log.json."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if AUDIT_LOG.exists():
        try:
            existing = json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.insert(0, entry)
    AUDIT_LOG.write_text(
        json.dumps(existing[:500], indent=2, default=str),
        encoding="utf-8",
    )


def _short_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]
