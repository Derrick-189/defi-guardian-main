#!/usr/bin/env python3
"""
DeFi Guardian — Verification Worker
Processes verification jobs from the queue.
For production, consider using RQ + Redis for better scalability.
"""

import os
import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime

# Add web_portal to path
PORTAL_DIR = Path(__file__).parent / "web_portal"
sys.path.insert(0, str(PORTAL_DIR))

# Simple SQLite-based queue (for development)
# In production, replace with RQ + Redis

# Import queue manager
from queue_manager import init_queue, submit_job, get_pending_job, complete_job

def run_verification_job(job):
    """Run a verification job."""
    from verification_server import run_real_verification

    job_id, tool, contract_path, spec_path, output_dir = job[1], job[2], job[3], job[4], job[5]

    try:
        result = run_real_verification(
            tool=tool,
            contract_path=contract_path,
            spec_path=spec_path,
            output_dir=output_dir
        )

        # --- 1. Parse traces if a trail file was produced ---
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from trace_parsers import get_parser
            parser = get_parser(tool)
            if parser and result.get("trail_path") and Path(result["trail_path"]).exists():
                parsed = parser.parse_trace(result.get("trail_path", ""), result.get("trail_path", ""))
                if parsed:
                    parsed_json_path = Path(output_dir) / "parsed_trace.json"
                    import json as _json
                    parsed_payload = parsed.to_dict() if hasattr(parsed, "to_dict") else {"steps": []}
                    with open(parsed_json_path, "w") as pf:
                        _json.dump(parsed_payload, pf, indent=2)
                    result["parsed_trace_path"] = str(parsed_json_path)
                    # Attach parsed trace JSON for DB storage
                    try:
                        result["trace_data"] = _json.dumps(parsed_payload)
                    except Exception:
                        result["trace_data"] = None
        except Exception as pe:
            print(f"Trace parsing failed: {pe}")

        # --- 2. Persist result to the portal's audit_history table ---
        try:
            audit_db_path = Path(__file__).parent / "web_portal" / "defi_guardian.db"
            conn = sqlite3.connect(str(audit_db_path))
            
            # Check if record already exists for this job_id
            existing = conn.execute("SELECT id FROM audit_history WHERE job_id = ?", (job_id,)).fetchone()
            
            if existing:
                # Update including trace_data if available
                conn.execute("""
                    UPDATE audit_history SET
                        status = ?,
                        states_explored = ?,
                        transitions = ?,
                        depth_reached = ?,
                        verification_output = ?,
                        report_path = ?,
                        trace_data = ?,
                        audit_date = CURRENT_TIMESTAMP
                    WHERE job_id = ?
                """, (
                    "PASS" if not result.get("counterexample_found") else "FAIL",
                    result.get("states_stored", 0),
                    result.get("transitions", 0),
                    result.get("depth", 0),
                    result.get("stdout", "")[:4000],
                    result.get("trail_path", "") or "",
                    result.get("trace_data"),
                    job_id
                ))
            else:
                conn.execute("""
                    INSERT INTO audit_history
                      (filename, file_type, tool_used, status,
                       states_explored, transitions, depth_reached,
                       verification_output, report_path, trace_data, job_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    Path(contract_path).name,
                    Path(contract_path).suffix or "",
                    tool.upper(),
                    "PASS" if not result.get("counterexample_found") else "FAIL",
                    result.get("states_stored", 0),
                    result.get("transitions", 0),
                    result.get("depth", 0),
                    result.get("stdout", "")[:4000],
                    result.get("trail_path", "") or "",
                    result.get("trace_data"),
                    job_id
                ))
            conn.commit()
            conn.close()
        except Exception as de:
            print(f"DB insert failed: {de}")

        # --- 3. Mark job complete in queue DB ---
        complete_job(job_id, result)
        print(f"Job {job_id} completed: {result.get('status')}")

        # --- 4. Remove intermediate SPIN compilation artefacts to save space ---
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

def main():
    print("Starting DeFi Guardian Verification Worker...")
    print("Processing jobs from the queue.")
    print("Press Ctrl+C to stop.")
    print()

    init_queue()

    while True:
        job = get_pending_job()
        if job:
            print(f"Processing job {job[1]} ({job[2]})...")
            run_verification_job(job)
        else:
            time.sleep(1)  # Wait for new jobs

if __name__ == "__main__":
    main()
