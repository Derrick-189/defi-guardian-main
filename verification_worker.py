#!/usr/bin/env python3
"""
DeFi Guardian — Verification Worker
Processes verification jobs from the queue.
For production, consider using RQ + Redis for better scalability.
"""

import os
import sys
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask

# Add root and web_portal to path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "web_portal"))

def _augment_path():
    import os
    home = Path.home()
    extra_paths = [
        str(home / ".elan" / "bin"),
        str(home / ".cargo" / "bin"),
        str(home / ".opam" / "default" / "bin"),
        str(home / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/verus",
    ]
    current_path = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in current_path:
            current_path = f"{p}{os.pathsep}{current_path}"
    os.environ["PATH"] = current_path

_augment_path()

from web_portal.config import config_by_name
from web_portal.audit_db import db, AuditHistory, init_db

app = Flask(__name__)
env = os.environ.get("FLASK_ENV", "dev")
app.config.from_object(config_by_name[env])
init_db(app)
from queue_manager import init_queue, get_pending_job, complete_job, QUEUE_DB

_STALE_SECONDS = 300  # reset jobs stuck in 'running' for > 5 min

def reset_stale_running():
    """Reset jobs that have been stuck in 'running' state for too long."""
    conn = sqlite3.connect(str(QUEUE_DB))
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT id, job_id, started_at FROM jobs WHERE status = 'running'"
    ).fetchall()
    reset_ids = []
    for row in rows:
        started_str = row[2]
        if started_str:
            try:
                started = datetime.fromisoformat(started_str)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if (now - started).total_seconds() > _STALE_SECONDS:
                    reset_ids.append(row[0])
            except ValueError:
                reset_ids.append(row[0])
    if reset_ids:
        placeholders = ",".join("?" * len(reset_ids))
        conn.execute(
            f"UPDATE jobs SET status = 'pending', started_at = NULL WHERE id IN ({placeholders})",
            reset_ids,
        )
        conn.commit()
        print(f"reset_stale_running: reset {len(reset_ids)} stale job(s) {reset_ids}")
    conn.close()

def run_verification_job(job):
    """Run a verification job and update the central database."""
    from web_portal.verification_server import run_real_verification

    job_id, tool, contract_path, spec_path, output_dir = job[1], job[2], job[3], job[4], job[5]

    try:
        result = run_real_verification(
            tool=tool,
            contract_path=contract_path,
            spec_path=spec_path,
            output_dir=output_dir
        )

        # Ensure success key exists
        if "success" not in result:
            if result.get("status") in ("error", "failed", "timeout"):
                result["success"] = False
            else:
                # For spin/certora etc which use counterexample_found
                result["success"] = not result.get("counterexample_found", False)

        # --- 1. Parse traces and rules if a parser is available ---
        trace_data = None
        rules = []
        try:
            from web_portal.trace_parsers import get_parser
            parser = get_parser(tool)
            stdout = result.get("stdout", result.get("output", ""))
            
            if parser:
                # Parse rules to determine status accurately
                rules = parser.parse_rules(stdout)
                
                if result.get("trail_path") and Path(result["trail_path"]).exists():
                    parsed = parser.parse_trace(result.get("trail_path", ""), result.get("trail_path", ""))
                    if parsed:
                        import json as _json
                        parsed_payload = parsed.to_dict() if hasattr(parsed, "to_dict") else {"steps": []}
                        trace_data = _json.dumps(parsed_payload)
                        # Also save to physical file
                        parsed_json_path = Path(output_dir) / "parsed_trace.json"
                        with open(parsed_json_path, "w") as pf:
                            _json.dump(parsed_payload, pf, indent=2)
                        result["parsed_trace_path"] = str(parsed_json_path)
            
            # --- Generate state graph for SPIN ---
            if tool.lower() == "spin":
                try:
                    from web_portal.utils import _load_state_graph
                    # Simple heuristic: if we have steps, we can build a basic graph
                    if parsed and hasattr(parsed, "steps") and parsed.steps:
                        nodes = []
                        edges = []
                        seen_states = set()
                        for i, step in enumerate(parsed.steps):
                            s_id = step.state or f"S{i}"
                            if s_id not in seen_states:
                                nodes.append({"id": s_id, "label": s_id, "type": "error" if step.is_error else "normal"})
                                seen_states.add(s_id)
                            if i > 0:
                                prev_s = parsed.steps[i-1].state or f"S{i-1}"
                                edges.append({"from": prev_s, "to": s_id, "label": step.action[:20]})
                        
                        graph = {"nodes": nodes, "edges": edges}
                        graph_file = Path(output_dir) / "state_graph.json"
                        with open(graph_file, "w") as gf:
                            _json.dump(graph, gf, indent=2)
                        
                        # Also update the global one for the Visualization page
                        global_graph = Path(ROOT_DIR) / "generated" / "reports" / "state_graph.json"
                        global_graph.parent.mkdir(parents=True, exist_ok=True)
                        with open(global_graph, "w") as gf:
                            _json.dump(graph, gf, indent=2)
                    else:
                        # Clear global graph if no trace (e.g. PASS)
                        global_graph = Path(ROOT_DIR) / "generated" / "reports" / "state_graph.json"
                        if global_graph.exists():
                            with open(global_graph, "w") as gf:
                                _json.dump({"nodes": [], "edges": []}, gf)
                except Exception as ge:
                    print(f"State graph generation failed: {ge}")

        except Exception as pe:
            print(f"Trace parsing failed: {pe}")

        if rules:
            result["ltl_results"] = rules

        # --- 2. Persist result using SQLAlchemy (Supports Postgres/SQLite) ---
        with app.app_context():
            # Try to find by Job ID first
            audit = AuditHistory.query.filter_by(job_id=job_id).first()
            
            if not audit:
                # Try to find a PENDING audit with matching filename and tool if job_id is missing
                # This helps link jobs created by the web portal before the ID was known
                audit = AuditHistory.query.filter_by(
                    filename=Path(contract_path).name,
                    tool_used=tool.upper(),
                    status="PENDING"
                ).order_by(AuditHistory.audit_date.desc()).first()

            # Determine final status
            if rules:
                has_failed = any(r.get("status") == "VIOLATED" or r.get("errors", 0) > 0 for r in rules)
            else:
                has_failed = not result.get("success", True) or result.get("errors_count", 0) > 0

            if result.get("status") in ("error", "failed", "timeout"):
                final_status = "ERROR"
            else:
                final_status = "FAIL" if has_failed else "PASS"

            if audit:
                audit.status = final_status
                if rules:
                    import json as _json
                    audit.ltl_properties = _json.dumps(rules)

                audit.states_explored = result.get("states_stored", 0)
                audit.transitions = result.get("transitions", 0)
                audit.depth_reached = result.get("depth", 0)
                audit.verification_output = result.get("stdout", result.get("output", ""))[:10000]
                audit.report_path = result.get("trail_path", "") or ""
                audit.trace_data = trace_data
                audit.job_id = job_id
                audit.audit_date = datetime.now(timezone.utc)
                
                # Try to load source code
                try:
                    with open(contract_path, "r", encoding="utf-8", errors="replace") as sf:
                        audit.source_code = sf.read()
                except Exception:
                    pass
            else:
                # Create new record if none found
                s_code = ""
                try:
                    with open(contract_path, "r", encoding="utf-8", errors="replace") as sf:
                        s_code = sf.read()
                except Exception:
                    pass

                import json as _json
                audit = AuditHistory(
                    filename=Path(contract_path).name,
                    file_type=Path(contract_path).suffix or "",
                    tool_used=tool.upper(),
                    status=final_status,
                    states_explored=result.get("states_stored", 0),
                    transitions=result.get("transitions", 0),
                    depth_reached=result.get("depth", 0),
                    ltl_properties=_json.dumps(rules) if rules else "[]",
                    verification_output=result.get("stdout", result.get("output", ""))[:10000],
                    report_path=result.get("trail_path", "") or "",
                    trace_data=trace_data,
                    source_code=s_code,
                    job_id=job_id
                )
                db.session.add(audit)
            
            db.session.commit()
            print(f"Database updated for audit {audit.id}")

        # --- 3. Update global state for UI visibility ---
        try:
            # FIX: Ensure we use the correct project-level state file
            state_path = Path(ROOT_DIR) / "verification_state.json"
            state = {}
            if state_path.exists():
                try:
                    state = _json.loads(state_path.read_text(encoding="utf-8"))
                except: pass
            
            t_low = tool.lower()
            state[t_low] = {
                "status": audit.status,
                "timestamp": audit.audit_date.isoformat() if audit.audit_date else "",
                "model_name": Path(contract_path).name,
                "success": audit.status == "PASS",
                "progress": 100,
                "ltl_results": result.get("ltl_results", []),
                "states_stored": result.get("states_stored", 0),
                "transitions": result.get("transitions", 0),
                "depth": result.get("depth", 0)
            }
            state["active_tool"] = tool.upper()
            state["active_status"] = audit.status
            state["success"] = audit.status == "PASS"
            state["ltl_results"] = result.get("ltl_results", [])
            
            state_path.write_text(_json.dumps(state, indent=2), encoding="utf-8")
            print(f"Global state updated for {tool} at {state_path}")
        except Exception as se:
            print(f"Global state update failed: {se}")

        # --- 4. Mark job complete in queue DB ---
        complete_job(job_id, result)
        print(f"Job {job_id} completed: {result.get('status')}")

        # --- 5. Notify UI via SocketIO ---
        try:
            from web_portal.app import socketio
            event_data = {
                "tool": tool.upper(),
                "status": audit.status,
                "filename": Path(contract_path).name,
                "states": audit.states_explored,
                "transitions": audit.transitions,
                "depth": audit.depth_reached,
                "ltl_results": result.get("ltl_results", []),
                "job_id": job_id
            }
            socketio.emit("verification_complete", event_data, namespace="/")
            
            # Also emit a general state update
            state_path = Path(ROOT_DIR) / "verification_state.json"
            if state_path.exists():
                import json as _json
                state = _json.loads(state_path.read_text(encoding="utf-8"))
                socketio.emit("verification_update", state, namespace="/")
            
            print(f"SocketIO notification sent for {tool}")
        except Exception as e:
            print(f"SocketIO notification failed: {e}")

        # --- 6. Cleanup intermediate files ---
        try:
            for tmp_ext in ["pan.c", "pan.b", "pan.m", "pan.p", "pan.t", "pan"]:
                tmp_file = Path(output_dir) / tmp_ext
                if tmp_file.exists():
                    tmp_file.unlink()
        except Exception:
            pass

    except Exception as e:
        error_result = {"status": "error", "message": str(e)}
        complete_job(job_id, error_result)
        print(f"Job {job_id} failed: {e}")
        
        # Also update AuditHistory so UI doesn't hang in PENDING
        try:
            with app.app_context():
                audit = AuditHistory.query.filter_by(job_id=job_id).first()
                if not audit:
                    audit = AuditHistory.query.filter_by(
                        filename=Path(job[3]).name,
                        tool_used=job[2].upper(),
                        status="PENDING"
                    ).order_by(AuditHistory.audit_date.desc()).first()
                
                if audit:
                    audit.status = "ERROR"
                    audit.verification_output = f"Worker crashed: {str(e)}"
                    db.session.commit()
        except Exception as db_e:
            print(f"Failed to update AuditHistory for failed job: {db_e}")

def main():
    print("Starting DeFi Guardian Verification Worker...")
    print("Processing jobs from the queue.")
    print("Press Ctrl+C to stop.")
    print()

    init_queue()
    reset_stale_running()

    while True:
        try:
            job = get_pending_job()
            if job:
                print(f"Processing job {job[1]} ({job[2]})...")
                run_verification_job(job)
            else:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nWorker stopped by user.")
            break
        except Exception as e:
            print(f"Worker loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
