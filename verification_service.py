"""
Verification Service — exposes the desktop verification engine as HTTP API.
Enables the web portal to use real verification instead of simulation.
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

app = Flask(__name__)
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))
from web_portal.audit_db import get_db


def _ensure_dirs():
    """Ensure verification output directory exists."""
    results_dir = PROJECT_DIR / "verification_results"
    results_dir.mkdir(exist_ok=True)
    return results_dir


@app.route("/health", methods=["GET"])
def health():
    """Health check for verification service."""
    return jsonify({"status": "ok", "service": "verification_service"})


@app.route("/verify", methods=["POST"])
def verify():
    """
    Main verification endpoint.
    
    Accepts:
    - contract: uploaded contract file or None
    - tool: verification tool (spin, verus, certora, coq, lean)
    - spec_text: specification as text
    - contract_text: contract source as text (if not uploading file)
    
    Returns:
    - status: completed | error | timeout
    - tool: the tool used
    - stdout: verifier output
    - stderr: verifier errors
    - counterexample_found: bool
    - trail_path: path to .trail file if counterexample exists
    - job_id: unique job identifier
    """
    try:
        tool = request.form.get("tool", "").lower()
        spec_text = request.form.get("spec_text", "")
        contract_text = request.form.get("contract_text", "")
        
        if not tool:
            return jsonify({"status": "error", "message": "Tool is required"}), 400
        
        results_dir = _ensure_dirs()
        job_dir = tempfile.mkdtemp(dir=results_dir)
        job_id = os.path.basename(job_dir)
        
        # Save contract
        contract_path = None
        if "contract" in request.files:
            file = request.files["contract"]
            if file:
                contract_path = os.path.join(job_dir, file.filename)
                file.save(contract_path)
        elif contract_text:
            # Infer file extension from tool
            ext = ".pml" if tool == "spin" else ".rs" if tool in ("verus", "kani") else ".sol"
            contract_path = os.path.join(job_dir, f"contract{ext}")
            with open(contract_path, "w") as f:
                f.write(contract_text)
        
        if not contract_path or not os.path.exists(contract_path):
            return jsonify({"status": "error", "message": "No contract provided"}), 400
        
        # Save spec if provided
        spec_path = None
        if spec_text:
            spec_path = os.path.join(job_dir, "spec.txt")
            with open(spec_path, "w") as f:
                f.write(spec_text)
        
        # Run verification
        result = run_real_verification(
            tool=tool,
            contract_path=contract_path,
            spec_path=spec_path,
            output_dir=job_dir
        )
        
        result["job_id"] = job_id
        result["created_at"] = datetime.utcnow().isoformat()
        
        # Save to audit database
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Extract trail file path if it exists
            trail_path = None
            if result.get("counterexample_found"):
                for file in os.listdir(job_dir):
                    if file.endswith(".trail"):
                        trail_path = os.path.join(job_dir, file)
                        break

            # Try to parse trail into structured JSON for DB storage
            trace_data_payload = None
            try:
                if trail_path and os.path.exists(trail_path):
                    from web_portal.trace_parsers import get_parser
                    parser = get_parser(result.get('tool',''))
                    if parser:
                        parsed = parser.parse_trace(trail_path, trail_path)
                        if parsed:
                            trace_data_payload = json.dumps(parsed.to_dict())
            except Exception:
                trace_data_payload = None
            
            # Save audit record
                cursor.execute("""
                INSERT INTO audit_history 
                (filename, file_type, tool_used, status, verification_output, report_path, trace_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                filename or "contract",
                os.path.splitext(filename or "contract")[1] or "",
                tool.upper(),
                "PASS" if result.get("status") == "completed" and not result.get("counterexample_found") else "FAIL",
                result.get("stdout", "") + "\n" + result.get("stderr", ""),
                trail_path or "",
                trace_data_payload,
            ))
            
            audit_id = cursor.lastrowid
            result["audit_id"] = audit_id
            
            conn.commit()
            conn.close()
        except Exception as db_e:
            print(f"Database save failed: {db_e}")
            # Continue without failing the verification
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def run_real_verification(tool, contract_path, spec_path, output_dir):
    """
    Execute real verifier based on tool type.
    
    Args:
        tool: verification tool name
        contract_path: path to contract file
        spec_path: path to spec file (optional)
        output_dir: directory for outputs
    
    Returns:
        dict with status, tool, stdout, stderr, counterexample_found, trail_path
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
        # Translate Promela to C
        subprocess.run(
            ["spin", "-a", contract_path],
            cwd=output_dir,
            capture_output=True,
            timeout=60
        )
        
        pan_file = os.path.join(output_dir, "pan")
        
        # Compile pan.c
        compile_result = subprocess.run(
            ["gcc", "-O2", "-o", pan_file, "pan.c"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if compile_result.returncode != 0:
            return {
                "status": "error",
                "tool": "spin",
                "stderr": compile_result.stderr
            }
        
        # Run verification
        result = subprocess.run(
            [pan_file, "-a"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        trail_path = os.path.join(output_dir, f"{os.path.basename(contract_path)}.trail")
        trail_exists = os.path.exists(trail_path)
        
        return {
            "status": "completed",
            "tool": "spin",
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:10000],
            "counterexample_found": trail_exists,
            "trail_path": trail_path if trail_exists else None,
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "spin",
            "message": f"SPIN execution failed: {str(e)}"
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
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:10000],
            "counterexample_found": "error" in result.stderr.lower() or result.returncode != 0,
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "verus",
            "message": f"Verus execution failed: {str(e)}"
        }


def run_certora(contract_path, spec_path, output_dir):
    """Execute Certora prover."""
    try:
        if not spec_path:
            return {
                "status": "error",
                "tool": "certora",
                "message": "Certora requires a specification file"
            }
        
        result = subprocess.run(
            ["certoraRun", contract_path, "--specs", spec_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        return {
            "status": "completed",
            "tool": "certora",
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:10000],
            "counterexample_found": "counterexample" in result.stdout.lower(),
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "certora",
            "message": f"Certora execution failed: {str(e)}"
        }


def run_coq(contract_path, output_dir):
    """Execute Coq proof checker."""
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
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:10000],
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "coq",
            "message": f"Coq execution failed: {str(e)}"
        }


def run_lean(contract_path, output_dir):
    """Execute Lean proof checker."""
    try:
        result = subprocess.run(
            ["lake", "build"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        return {
            "status": "completed",
            "tool": "lean",
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:10000],
            "counterexample_found": result.returncode != 0,
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "lean",
            "message": f"Lean execution failed: {str(e)}"
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
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:10000],
            "counterexample_found": "FAILED" in result.stdout or result.returncode != 0,
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        return {
            "status": "error",
            "tool": "kani",
            "message": f"Kani execution failed: {str(e)}"
        }


@app.route("/job/<job_id>", methods=["GET"])
def get_job(job_id):
    """Retrieve job metadata and results."""
    try:
        results_dir = PROJECT_DIR / "verification_results"
        job_dir = results_dir / job_id
        metadata_path = job_dir / "metadata.json"
        
        if not metadata_path.exists():
            return jsonify({"error": "Job not found"}), 404
        
        with open(metadata_path) as f:
            metadata = json.load(f)
        
        return jsonify(metadata)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("VERIFICATION_SERVICE_PORT", "9000"))
    app.run(host="0.0.0.0", port=port, debug=False)
