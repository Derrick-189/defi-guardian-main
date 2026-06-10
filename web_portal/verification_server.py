"""
DeFi Guardian — Verification Server
Exposes the desktop verification engine as an HTTP API for the web portal.
"""

from flask import Flask, request, jsonify, send_file
import os
import sys
import json
import subprocess
import tempfile
import shutil
import re
from datetime import datetime
from pathlib import Path
import uuid
import sqlite3
import ast
from functools import wraps

app = Flask(__name__)


def normalize_promela_proctype(content: str) -> str:
    """
    Ensure SPIN-compatible proctype declarations include parentheses.
    Some SPIN versions require `proctype P() { ... }` instead of `proctype P { ... }`.
    """
    return re.sub(r'(?m)^(\s*(?:active\s+)?proctype\s+\w+)(?!\s*\()\s*\{', r'\1() {', content)

# Token authentication
VSERVER_TOKEN = os.environ.get("VSERVER_TOKEN")

def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if VSERVER_TOKEN:
            token = request.headers.get("X-VServer-Token")
            if token != VSERVER_TOKEN:
                return jsonify({"status": "error", "message": "Invalid or missing VSERVER_TOKEN"}), 401
        return f(*args, **kwargs)
    return decorated

# Path setup
PORTAL_DIR = Path(__file__).parent
PROJECT_DIR = PORTAL_DIR.parent
RESULTS_DIR = PORTAL_DIR / "verification_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Augment PATH for verification tools
def _augment_path():
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

# Import trace parsers — use explicit file load to avoid the root
# trace_parsers/ package shadowing web_portal/trace_parsers.py
import importlib.util as _ilu
_tp_path = PORTAL_DIR / "trace_parsers.py"
_tp_spec = _ilu.spec_from_file_location("web_portal.trace_parsers", _tp_path)
_tp_mod  = _ilu.module_from_spec(_tp_spec)
sys.modules["web_portal.trace_parsers"] = _tp_mod
sys.modules["trace_parsers"] = _tp_mod
_tp_spec.loader.exec_module(_tp_mod)
get_parser = _tp_mod.get_parser
# Make translator available (resides in project root)
try:
    sys.path.insert(0, str(PROJECT_DIR))
    from translator import DeFiTranslator, VerifiedTranslator
except Exception:
    DeFiTranslator = None
    VerifiedTranslator = None


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "verification_server"})


@app.route("/verify", methods=["POST"])
@require_token
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

        # Save contract (raw input). We'll attempt to translate if needed below.
        contract_path = None
        filename = "contract"
        raw_contract_path = None
        if "contract" in request.files:
            file = request.files["contract"]
            if file and file.filename:
                filename = file.filename
                raw_contract_path = job_dir / filename
                file.save(str(raw_contract_path))
        elif contract_text:
            # Save raw text first; detect language later
            form_filename = request.form.get("filename", "contract.pml")
            raw_contract_path = job_dir / form_filename
            with open(raw_contract_path, "w", encoding="utf-8") as f:
                f.write(contract_text)

        # If we couldn't persist the contract, error
        if not raw_contract_path or not raw_contract_path.exists():
            return jsonify({"status": "error", "message": "No contract provided"}), 400

        # Determine file type by extension or simple content heuristics
        suffix = raw_contract_path.suffix.lower()
        try:
            with open(raw_contract_path, 'r', encoding='utf-8') as rf:
                raw_content = rf.read()
        except Exception:
            raw_content = ""

        is_sol = False
        is_rs = False
        if suffix == '.sol' or 'contract ' in raw_content[:200].lower() or 'pragma solidity' in raw_content.lower():
            is_sol = True
        if suffix == '.rs' or re.search(r'fn\s+main|crate\b|extern\s+crate', raw_content[:200]):
            is_rs = True

        # If input is a Solidity or Rust source, translate to Promela for SPIN
        contract_path = None
        if is_sol or is_rs:
            if DeFiTranslator is None:
                # Translator not importable; fall back to saving raw and let worker handle
                contract_path = raw_contract_path
            else:
                try:
                    if is_sol:
                        if VerifiedTranslator and hasattr(VerifiedTranslator, 'translate_with_proof'):
                            translated_content, _ = VerifiedTranslator().translate_with_proof(raw_content)
                        else:
                            translated_content = DeFiTranslator.translate_solidity(raw_content)
                    else:
                        translated_content = DeFiTranslator.translate_rust(raw_content)

                    # If custom spec_text provided, inject it into the translated model
                    if spec_text:
                        cleaned = re.sub(r'ltl\s+\w+\s*\{[^}]*\}', '', translated_content, flags=re.DOTALL)
                        translated_content = cleaned + "\n\n/* === CUSTOM SPECIFICATIONS === */\n" + spec_text

                    translated_content = normalize_promela_proctype(translated_content)
                    contract_path = job_dir / "contract_translated.pml"
                    with open(contract_path, 'w', encoding='utf-8') as tf:
                        tf.write(translated_content)
                    filename = contract_path.name
                except Exception as te:
                    # On translation failure, save raw and continue (worker may attempt translation)
                    contract_path = raw_contract_path
        else:
            # Treat as already a model (.pml) or unknown text — save as .pml
            contract_path = job_dir / "contract.pml"
            if spec_text:
                cleaned = re.sub(r'ltl\s+\w+\s*\{[^}]*\}', '', raw_content, flags=re.DOTALL)
                raw_content = cleaned + "\n\n/* === CUSTOM SPECIFICATIONS === */\n" + spec_text
            raw_content = normalize_promela_proctype(raw_content)
            with open(contract_path, 'w', encoding='utf-8') as f:
                f.write(raw_content)

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
            # Use original source for tools that need it, otherwise translated model
            contract_path=str(raw_contract_path if tool in ('certora', 'kani', 'verus', 'prusti', 'creusot') else contract_path),
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
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e), "type": type(e).__name__}), 500


@app.route("/job/<job_id>", methods=["GET"])
@require_token
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
@require_token
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
@require_token
def download_artifact(job_id, filename):
    """Download an individual artifact file."""
    try:
        job_dir = RESULTS_DIR / job_id
        file_path = job_dir / filename
        if not file_path.exists() or not file_path.is_file():
            return jsonify({"status": "error", "message": "File not found"}), 404

        return send_file(str(file_path), as_attachment=True)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def run_real_verification(tool, contract_path, spec_path, output_dir):
    """
    Execute real verifier based on tool type with file type awareness.
    """
    try:
        tool = tool.lower()
        # Determine file type
        suffix = Path(contract_path).suffix.lower()
        is_sol = suffix == '.sol'
        is_rs = suffix == '.rs'

        # Tool-to-language compatibility check
        rust_only_tools = ('kani', 'verus', 'prusti', 'creusot')
        solidity_only_tools = ('certora',)

        if tool in rust_only_tools and not is_rs:
            return {
                "status": "error",
                "success": False,
                "tool": tool,
                "output": f"Tool {tool.upper()} only supports Rust files (.rs), but got {suffix}"
            }

        if tool in solidity_only_tools and not is_sol:
            return {
                "status": "error",
                "success": False,
                "tool": tool,
                "output": f"Tool {tool.upper()} only supports Solidity files (.sol), but got {suffix}"
            }

        result = None
        if tool == "spin":
            result = run_spin(contract_path, spec_path, output_dir)
        elif tool == "spinspider":
            result = run_spinspider(contract_path, output_dir)
        elif tool == "idot":
            result = run_idot(contract_path, output_dir)
        elif tool == "erigone":
            result = run_erigone(contract_path, output_dir)
        elif tool == "verus":
            result = run_verus(contract_path, output_dir)
        elif tool == "certora":
            result = run_certora(contract_path, spec_path, output_dir)
        elif tool == "coq":
            result = run_coq(contract_path, output_dir)
        elif tool == "lean":
            result = run_lean(contract_path, output_dir)
        elif tool == "kani":
            result = run_kani(contract_path, output_dir)
        elif tool == "prusti":
            result = run_prusti(contract_path, output_dir)
        elif tool == "creusot":
            result = run_creusot(contract_path, output_dir)
        else:
            result = {
                "status": "error",
                "success": False,
                "message": f"Unsupported tool: {tool}"
            }

        # --- Post-process: Extract LTL results and determine status ---
        if result and ("stdout" in result or "output" in result):
            try:
                from trace_parsers import get_parser
                parser = get_parser(tool)
                if parser:
                    log_content = result.get("stdout", result.get("output", ""))
                    ltl_results = parser.parse_rules(log_content)
                    if ltl_results:
                        result["ltl_results"] = ltl_results
                        # Determine if any LTL property was violated
                        has_violation = any(r.get("status") == "VIOLATED" or r.get("errors", 0) > 0 for r in ltl_results)
                        if has_violation:
                            result["counterexample_found"] = True
                            result["success"] = False
                        else:
                            # If all LTL passed, we can say it's successful if no other error
                            if result.get("status") == "completed" and not result.get("counterexample_found", False):
                                result["success"] = True
            except Exception: pass
            
        return result
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "success": False,
            "tool": tool,
            "message": "Verification timed out after 300 seconds"
        }
    except Exception as e:
        return {
            "status": "error",
            "success": False,
            "tool": tool,
            "message": str(e)
        }


def run_spin(contract_path, spec_path, output_dir):
    """Execute SPIN model checker."""
    try:
        # Check if a separate specification file is provided and exists
        spin_contract_path = contract_path
        combined_used = False
        if spec_path and os.path.exists(spec_path):
            try:
                with open(contract_path, "r", encoding="utf-8", errors="replace") as f:
                    contract_content = f.read()
                with open(spec_path, "r", encoding="utf-8", errors="replace") as f:
                    spec_content = f.read()
                
                # Combine them
                combined_filename = "combined_" + os.path.basename(contract_path)
                combined_path = os.path.join(output_dir, combined_filename)
                with open(combined_path, "w", encoding="utf-8") as f:
                    f.write(contract_content)
                    f.write("\n\n/* Specifications */\n")
                    f.write(spec_content)
                spin_contract_path = combined_path
                combined_used = True
            except Exception as e:
                print(f"Error combining SPIN contract and spec: {e}")

        # Generate pan.c
        result1 = subprocess.run(
            ["spin", "-a", spin_contract_path],
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

        # If combined was used, rename the resulting combined trail to the expected filename
        if combined_used:
            generated_trail = os.path.join(output_dir, f"combined_{os.path.basename(contract_path)}.trail")
            expected_trail = os.path.join(output_dir, f"{os.path.basename(contract_path)}.trail")
            if os.path.exists(generated_trail):
                try:
                    if os.path.exists(expected_trail):
                        os.remove(expected_trail)
                    os.rename(generated_trail, expected_trail)
                except Exception as e:
                    print(f"Error renaming trail file: {e}")

        # Check for trail file or error indicators
        trail_path = None
        for f in os.listdir(output_dir):
            if f.endswith(".trail"):
                trail_path = os.path.join(output_dir, f)
                break

        full_stdout = (result1.stdout or "") + (result2.stdout or "") + (result3.stdout or "")
        full_stderr = (result1.stderr or "") + (result2.stderr or "") + (result3.stderr or "")
        
        has_error = "Error:" in full_stdout or "Error:" in full_stderr or result3.returncode != 0
        
        return {
            "status": "completed",
            "tool": "spin",
            "stdout": full_stdout,
            "stderr": full_stderr,
            "counterexample_found": trail_path is not None or has_error,
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


def run_spinspider(contract_path, output_dir):
    """Generate state space graph using SpinSpider."""
    try:
        # 1. Generate pan.c with -DDUMP
        subprocess.run(["spin", "-a", "-DDUMP", contract_path], cwd=output_dir, capture_output=True, timeout=30)
        
        # 2. Compile pan.c
        subprocess.run(["gcc", "-o", "pan", "pan.c"], cwd=output_dir, capture_output=True, timeout=30)
        
        # 3. Run pan to get dump
        with open(os.path.join(output_dir, "pan.dump"), "w") as f:
            subprocess.run(["./pan"], cwd=output_dir, stdout=f, timeout=60)
            
        # 4. Run SpinSpider
        graph_file = os.path.join(output_dir, "state_space.dot")
        with open(graph_file, "w") as f:
            subprocess.run(["spinspider", "pan.dump"], cwd=output_dir, stdout=f, timeout=30)
            
        # 5. Convert to PNG
        png_file = os.path.join(output_dir, "state_space.png")
        subprocess.run(["dot", "-Tpng", graph_file, "-o", png_file], cwd=output_dir, timeout=30)
        
        if os.path.exists(png_file):
            return {
                "status": "completed",
                "success": True,
                "tool": "spinspider",
                "message": "State space graph generated successfully",
                "artifact": "state_space.png"
            }
        return {"status": "error", "message": "Failed to generate PNG image"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def run_idot(contract_path, output_dir):
    """Run iDot visualizer (generates DOT output)."""
    try:
        graph_file = os.path.join(output_dir, "idot_graph.dot")
        with open(graph_file, "w") as f:
            subprocess.run(["idot", contract_path], cwd=output_dir, stdout=f, timeout=30)
            
        if os.path.exists(graph_file):
            return {
                "status": "completed",
                "success": True,
                "tool": "idot",
                "message": "iDot graph generated",
                "artifact": "idot_graph.dot"
            }
        return {"status": "error", "message": "Failed to generate iDot graph"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def run_erigone(contract_path, output_dir):
    """Execute Erigone model checker."""
    try:
        result = subprocess.run(
            ["erigone", contract_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        return {
            "status": "completed" if result.returncode == 0 else "failed",
            "success": result.returncode == 0,
            "tool": "erigone",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
        # Extract contract name
        contract_name = "Contract"
        try:
            with open(contract_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                match = re.search(r'contract\s+(\w+)', content)
                if match:
                    contract_name = match.group(1)
        except Exception:
            pass

        cmd = ["certoraRun", contract_path]
        if spec_path:
            cmd.extend(["--verify", f"{contract_name}:{spec_path}"])

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
            "counterexample_found": result.returncode != 0 or "counterexample" in result.stdout.lower() or "violated" in result.stdout.lower(),
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
    print(f"Starting verification server on port {port}")
    if VSERVER_TOKEN:
        print("Token authentication: ENABLED")
    else:
        print("Token authentication: DISABLED (Warning: Server is public!)")
    app.run(host="0.0.0.0", port=port, debug=False)
