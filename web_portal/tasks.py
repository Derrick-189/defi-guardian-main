import os, requests, json
from web_portal.audit_db import db, AuditHistory
from flask import current_app

# Make Celery optional: if Celery isn't installed, provide a synchronous
# fallback decorator so the rest of the codebase doesn't crash on import.
try:
    from celery import shared_task  # type: ignore
except Exception:
    # Simple fallback: a decorator that executes the function synchronously
    def shared_task(**kwargs):
        def _decorator(func):
            def _wrapper(*args, **inner_kwargs):
                return func(*args, **inner_kwargs)
            return _wrapper
        return _decorator

@shared_task(bind=True)
def run_verification_task(self, audit_id, tool, filename, contract_text, spec_text, verif_url, headers):
    # This task runs in a Celery worker with an app context
    audit = AuditHistory.query.get(audit_id)
    if not audit:
        return {"error": "Audit not found"}

    server_data = {
        "tool": tool.lower(),
        "contract_text": contract_text,
        "filename": filename,
        "spec_text": spec_text
    }

    try:
        resp = requests.post(
            f"{verif_url}/verify",
            data=server_data,
            headers=headers,
            timeout=300 # Longer timeout for heavy verifications
        )
        resp.raise_for_status()
        result = resp.json()

        # If the server accepted the job but didn't finish it yet, we need to poll
        if result.get("status") == "accepted" and result.get("job_id"):
            job_id = result.get("job_id")
            import time
            max_retries = 30 # 30 * 10s = 300s
            for _ in range(max_retries):
                time.sleep(10)
                job_resp = requests.get(f"{verif_url}/job/{job_id}", headers=headers, timeout=10)
                if job_resp.ok:
                    job_data = job_resp.json()
                    if job_data.get("status") in ("completed", "failed", "error"):
                        result = job_data.get("result", job_data)
                        break
            else:
                raise Exception("Verification timed out in Celery worker")

        # Update audit record
        audit.job_id = result.get("job_id", audit.job_id)
        # Check for results in various formats (direct or nested in result)
        res_data = result.get("result", result) if isinstance(result.get("result"), dict) else result
        
        status = "PASS" if not res_data.get("counterexample_found") else "FAIL"
        audit.status = status
        audit.states_explored = res_data.get("states_stored", 0)
        audit.transitions = res_data.get("transitions", 0)
        audit.depth_reached = res_data.get("depth", 0)
        audit.verification_output = res_data.get("stdout", "")[:10000]
        audit.report_path = res_data.get("trail_path", "") or ""
        # Persist the contract source so the Counterexample Source Code tab works
        if contract_text and not audit.source_code:
            audit.source_code = contract_text[:50000]
        
        db.session.commit()

        # ── Notify UI via SocketIO ───────────────────────────────────────────
        try:
            from web_portal.api_v1 import api_emit_event
            # We can't call the route directly easily, but we can reuse the logic
            # or better, just call a helper. For now, let's just emit.
            from web_portal.app import socketio
            event_data = {
                "tool": tool,
                "status": status,
                "filename": filename,
                "states": audit.states_explored,
                "transitions": audit.transitions,
                "depth": audit.depth_reached,
                "ltl_results": res_data.get("ltl_results", [])
            }
            socketio.emit("verification_complete", event_data)
            
            # Trigger state update
            from web_portal.api_v1 import load_state, save_state
            state = load_state()
            # (state update logic same as in api_emit_event)
            t_low = tool.lower()
            state[t_low] = {
                "status": status,
                "timestamp": audit.audit_date.isoformat() if audit.audit_date else "",
                "model_name": filename,
                "success": status == "PASS"
            }
            state["states_stored"] = audit.states_explored
            state["transitions"] = audit.transitions
            state["depth"] = audit.depth_reached
            state["model_name"] = filename
            state["success"] = status == "PASS"
            if "ltl_results" in res_data: state["ltl_results"] = res_data["ltl_results"]
            
            save_state(state)
            socketio.emit("verification_update", state)
        except Exception as e:
            print(f"SocketIO emit failed in task: {e}")

        return {"status": "success", "audit_id": audit_id}

    except Exception as e:
        audit.status = "ERROR"
        audit.verification_output = f"Task failed: {str(e)}"
        db.session.commit()
        return {"error": str(e)}
