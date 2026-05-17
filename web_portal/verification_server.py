"""
DeFi Guardian — Verification Server
Exposes the desktop verification engine as an HTTP API for the web portal.
"""

from flask import Flask, request, jsonify
import os
import sys
import json
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import uuid
import sqlite3
import ast

app = Flask(__name__)

# Path setup
PORTAL_DIR = Path(__file__).parent
PROJECT_DIR = PORTAL_DIR.parent
RESULTS_DIR = PORTAL_DIR / "verification_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Import trace parsers
sys.path.insert(0, str(PORTAL_DIR))
from trace_parsers import get_parser


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "verification_server"})


@app.route("/verify", methods=["POST"])
def verify():
    """
    Main verification endpoint.
    Accepts contract file, tool, and optional spec.
    Returns verification results with counterexamples.
    """
    try:
        # Get form data
        tool = request.form.get("tool", "").lower()
        spec_text = request.form.get("spec_text", "")
        contract_text = request.form.get("contract_text", "")

        if not tool:
            return jsonify({"status": "error", "message": "Tool is required"}), 400

        # Create job directory
        job_id = str(uuid.uuid4())[:8]
        job_dir = RESULTS_DIR / job_id
        job_dir.mkdir(exist_ok=True)

        # Save contract
        contract_path = None
        filename = "contract"
        if "contract" in request.files:
            file = request.files["contract"]
            if file and file.filename:
                filename = file.filename
                contract_path = job_dir / filename
                file.save(str(contract_path))
        elif contract_text:
            # Infer extension from tool
            ext = ".pml" if tool == "spin" else ".rs" if tool in ("verus", "kani", "prusti", "creusot") else ".sol"
            contract_path = job_dir / f"contract{ext}"
            with open(contract_path, "w") as f:
                f.write(contract_text)

        if not contract_path or not contract_path.exists():
            return jsonify({"status": "error", "message": "No contract provided"}), 400

        # Save spec if provided
        spec_path = None
        if "spec" in request.files:
            spec_file = request.files["spec"]
            if spec_file and spec_file.filename:
                spec_path = job_dir / spec_file.filename
                spec_file.save(str(spec_path))
        elif spec_text:
            spec_path = job_dir / "spec.txt"
            with open(spec_path, "w") as f:
                f.write(spec_text)

        # Submit job to queue instead of running synchronously
        from queue_manager import submit_job

        submit_job(
            job_id=job_id,
            tool=tool,
            contract_path=str(contract_path),
            spec_path=str(spec_path) if spec_path else None,
            output_dir=str(job_dir)
        )

        # Return job accepted response
        result = {
            "status": "accepted",
            "job_id": job_id,
            "message": "Verification job submitted to queue",
            "filename": filename,
            "tool": tool.upper()
        }
        return jsonify(result)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/job/<job_id>", methods=["GET"])
def get_job(job_id):
    """
    Return status and result for a queued verification job.
    Reads from verification_queue.db and also loads parsed_trace.json if present.
    """
    try:
        queue_db = PORTAL_DIR / "verification_queue.db"
        if not queue_db.exists():
            return jsonify({"status": "error", "message": "Queue database not found"}), 404

        conn = sqlite3.connect(str(queue_db))
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        conn.close()

        if not row:
            return jsonify({"status": "error", "message": "Job not found"}), 404

        # Column order: id, job_id, tool, contract_path, spec_path,
        #               output_dir, status, created_at, started_at, completed_at, result
        job_info = {
            "id": row[0],
            "job_id": row[1],
            "tool": row[2],
            "contract_path": row[3],
            "spec_path": row[4],
            "output_dir": row[5],
            "status": row[6],
            "created_at": row[7],
            "started_at": row[8],
            "completed_at": row[9],
            "result": None,
            "parsed_trace": None,
        }

        if row[6] == "completed" and row[10]:
            # result is stored as str(dict); try JSON first, then ast.literal_eval
            raw = row[10]
            try:
                job_info["result"] = json.loads(raw)
            except Exception:
                try:
                    job_info["result"] = ast.literal_eval(raw)
                except Exception:
                    job_info["result"] = raw

            # Load parsed_trace.json from the job output directory if present
            output_dir = row[5]
            if output_dir:
                parsed_trace_path = Path(output_dir) / "parsed_trace.json"
                if parsed_trace_path.exists():
                    try:
                        with open(parsed_trace_path) as pf:
                            job_info["parsed_trace"] = json.load(pf)
                    except Exception:
                        pass

        return jsonify(job_info)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/artifacts/<job_id>", methods=["GET"])
def list_artifacts(job_id):
    """
    List files present in a job's output directory.
    Useful for browsing verification artefacts (trails, logs, parsed traces, etc.).
    """
    try:
        job_dir = RESULTS_DIR / job_id
        if not job_dir.exists() or not job_dir.is_dir():
            return jsonify({"status": "error", "message": "Job directory not found"}), 404

        files = []
        for f in sorted(job_dir.iterdir()):
            if f.is_file():
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "path": str(f),
                    "ext": f.suffix.lstrip('.') or "txt",
                })

        return jsonify({"job_id": job_id, "artifacts": files})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/download/<job_id>/<filename>", methods=["GET"])
def download_artifact(job_id, filename):
    """Download an individual artifact file."""
    try:
        job_dir = RESULTS_DIR / job_id
        file_path = job_dir / filename
        if not file_path.exists() or not file_path.is_file():
            return jsonify({"status": "error", "message": "File not found"}), 404

        from flask import send_file
        return send_file(str(file_path), as_attachment=True)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def run_real_verification(tool, contract_path, spec_path, output_dir):
    """
    Execute real verifier based on tool type.
    """
    try:
        if tool == "spin":
            return run_spin(contract_path, spec_path, output_dir)
        elif tool == "verus":
            return run_verus(contract_path, output_dir)
        elif tool == "certora":
            return run_certora(contract_path, spec_path, output_dir)
        elif tool == "coq":
            return run_coq(contract_path, output_dir)
        elif tool == "lean":
            return run_lean(contract_path, output_dir)
        elif tool == "kani":
            return run_kani(contract_path, output_dir)
        elif tool == "prusti":
            return run_prusti(contract_path, output_dir)
        elif tool == "creusot":
            return run_creusot(contract_path, output_dir)
        else:
            return {
                "status": "error",
                "message": f"Unsupported tool: {tool}"
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "tool": tool,
            "message": "Verification timed out after 300 seconds"
        }
    except Exception as e:
        return {
            "status": "error",
            "tool": tool,
            "message": str(e)
        }


def run_spin(contract_path, spec_path, output_dir):
    """Execute SPIN model checker."""
    try:
        # Generate pan.c
        result1 = subprocess.run(
            ["spin", "-a", contract_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        pan_c_path = os.path.join(output_dir, "pan.c")
        if not os.path.exists(pan_c_path):
            return {
                "status": "error",
                "tool": "spin",
                "message": "Failed to generate pan.c",
                "stdout": result1.stdout,
                "stderr": result1.stderr
            }

        # Compile pan
        pan_path = os.path.join(output_dir, "pan")
        result2 = subprocess.run(
            ["gcc", "-o", pan_path, "pan.c"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result2.returncode != 0:
            return {
                "status": "error",
                "tool": "spin",
                "message": "Failed to compile pan",
                "stdout": result2.stdout,
                "stderr": result2.stderr
            }

        # Run verification
        result3 = subprocess.run(
            [pan_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        # Check for trail file
        trail_path = None
        for f in os.listdir(output_dir):
            if f.endswith(".trail"):
                trail_path = os.path.join(output_dir, f)
                break

        return {
            "status": "completed",
            "tool": "spin",
            "stdout": result3.stdout,
            "stderr": result3.stderr,
            "counterexample_found": trail_path is not None,
            "trail_path": trail_path,
            "return_code": result3.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "spin",
            "message": str(e)
        }


def run_verus(contract_path, output_dir):
    """Execute Verus verifier."""
    try:
        result = subprocess.run(
            ["verus", contract_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "verus",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "verus",
            "message": str(e)
        }


def run_certora(contract_path, spec_path, output_dir):
    """Execute Certora verifier."""
    try:
        cmd = ["certoraRun", contract_path]
        if spec_path:
            cmd.extend(["--spec", spec_path])

        result = subprocess.run(
            cmd,
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "certora",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "certora",
            "message": str(e)
        }


def run_coq(contract_path, output_dir):
    """Execute Coq verifier."""
    try:
        result = subprocess.run(
            ["coqc", contract_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "coq",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "coq",
            "message": str(e)
        }


def run_lean(contract_path, output_dir):
    """Execute Lean verifier."""
    try:
        result = subprocess.run(
            ["lean", contract_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "lean",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "lean",
            "message": str(e)
        }


def run_kani(contract_path, output_dir):
    """Execute Kani model checker."""
    try:
        result = subprocess.run(
            ["cargo", "kani", "--harness", "main"],
            cwd=os.path.dirname(contract_path) or output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "kani",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": "FAILED" in result.stdout or result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "kani",
            "message": str(e)
        }


def run_prusti(contract_path, output_dir):
    """Execute Prusti verifier."""
    try:
        result = subprocess.run(
            ["cargo", "prusti"],
            cwd=os.path.dirname(contract_path) or output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "prusti",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "prusti",
            "message": str(e)
        }


def run_creusot(contract_path, output_dir):
    """Execute Creusot verifier."""
    try:
        result = subprocess.run(
            ["cargo", "creusot"],
            cwd=os.path.dirname(contract_path) or output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            "status": "completed",
            "tool": "creusot",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "creusot",
            "message": str(e)
        }


if __name__ == "__main__":
    port = int(os.getenv("VERIFICATION_PORT", "9000"))
    app.run(host="0.0.0.0", port=port, debug=False)
