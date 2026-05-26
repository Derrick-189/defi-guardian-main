from flask import Blueprint, jsonify, request, session, current_app, Response
from flask_login import login_required, current_user
import os, json, re, requests, shutil, subprocess, time, sys
from pathlib import Path
from web_portal.audit_db import db, AuditHistory, User, sync_audit_log
from tasks import run_verification_task
from utils import _load_state_graph, _parse_spin_output_to_steps, _spin_recs, _property_category
from werkzeug.utils import secure_filename

# ── Ensure web_portal/trace_parsers.py is imported, NOT the root package ─────
# The project root contains a trace_parsers/ package that shadows the flat
# web_portal/trace_parsers.py module.  We resolve this once at import time so
# every lazy `from trace_parsers import get_parser` inside route functions
# always gets the correct, fully-featured flat module.
import importlib.util as _ilu
_tp_path = Path(__file__).parent / "trace_parsers.py"
_tp_spec = _ilu.spec_from_file_location("web_portal.trace_parsers", _tp_path)
_tp_mod  = _ilu.module_from_spec(_tp_spec)
# Register BEFORE exec_module so dataclass __module__ lookups resolve correctly
sys.modules["web_portal.trace_parsers"] = _tp_mod
sys.modules["trace_parsers"] = _tp_mod   # shadow the root package
_tp_spec.loader.exec_module(_tp_mod)
get_parser = _tp_mod.get_parser

api_v1 = Blueprint('api_v1', __name__)

PROJECT_DIR = Path(__file__).parent.parent
AUDIT_LOG_FILE = PROJECT_DIR / "generated" / "reports" / "audit_log.json"
VERIFICATION_STATE = PROJECT_DIR / "verification_state.json"

def load_state() -> dict:
    if VERIFICATION_STATE.exists():
        try:
            return json.loads(VERIFICATION_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_state(state: dict):
    try:
        # Use absolute path to project root
        p = Path("/home/slade/defi-guardian-main/verification_state.json")
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"DEBUG: State saved to {p}")
    except Exception as e:
        print(f"DEBUG: State save failed: {e}")

def _get_verif_url():
    # Priority: Env var > Config > Hardcoded default
    env_url = os.environ.get("VERIFICATION_SERVER_URL")
    if env_url: return env_url
    
    config_url = current_app.config.get("VSERVER_URL")
    if config_url: return config_url

    host = request.headers.get("Host", "127.0.0.1")
    if any(local in host for local in ["localhost", "127.0.0.1"]):
        return "http://127.0.0.1:9000"
    return os.environ.get("REMOTE_VERIFICATION_URL", "http://127.0.0.1:9000")

def _get_verif_headers():
    headers = {}
    token = os.environ.get("VSERVER_TOKEN")
    if token: headers["X-VServer-Token"] = token
    return headers

def _load_verification_content(output_path: str, report_path: str = "", audit_id: int = None) -> str:
    """
    Load verification output content.

    Resolution order:
    1. If it's already multi-line content (not a path), return it directly.
    2. Try the path as-is (works locally / same machine).
    3. Re-anchor the path relative to PROJECT_DIR using known path markers
       (handles desktop paths that differ from Render's /app prefix).
    4. If audit_id is provided, fall back to reading verification_output
       directly from the DB row — this is the Render ephemeral-disk workaround
       for desktop-synced records whose log files don't exist on the server.
    5. Return empty string so parsers degrade gracefully instead of receiving
       a raw file path as "content".
    """
    if not output_path:
        return ""

    # Already inline content (has newlines or is long) — return directly
    if "\n" in output_path or len(output_path) > 600:
        return output_path

    # Virtual DB path — not handled here
    if output_path.startswith("db://"):
        return output_path

    def _try_read(p: Path) -> str | None:
        if p.exists() and p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return None
        return None

    # 1. Direct path
    content = _try_read(Path(output_path))
    if content is not None:
        return content

    # 2. Relative to PROJECT_DIR
    content = _try_read(PROJECT_DIR / output_path)
    if content is not None:
        return content

    # 3. Re-anchor using known path markers (desktop path → server path)
    for marker in ["logs/", "generated/", "uploads/", "verification/", "console_exports/"]:
        if marker in output_path:
            rel_part = output_path.split(marker)[-1]
            content = _try_read(PROJECT_DIR / marker.strip("/") / rel_part)
            if content is not None:
                return content

    # 4. Render ephemeral-disk fallback: re-read from DB if we have the audit id
    #    The content may have been inlined by the updated sync_audit_log().
    if audit_id:
        try:
            row = AuditHistory.query.get(audit_id)
            if row and row.verification_output:
                vo = row.verification_output
                # Only use it if it looks like real content, not another path
                if "\n" in vo or len(vo) > 600:
                    return vo
        except Exception:
            pass

    # 5. Nothing worked — return empty so parsers don't receive a raw path
    return ""

@api_v1.route("/active/current")
@login_required
def api_active_current():
    """
    Return the most recent audit for the logged-in user (or any public audit),
    merged with the global verification_state.json. 
    Aggregates results for ALL tools run on the same file in the most recent batch.
    """
    u_id = current_user.get_id()
    user_id = int(u_id) if u_id else None

    # 1. Get the single most recent audit to identify the current file and time
    latest = AuditHistory.query.filter(
        (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
    ).order_by(AuditHistory.audit_date.desc()).first()

    state = load_state()

    if latest:
        # 2. Find all audits for the same file within a 15-minute window of the latest audit
        # This groups a "suite" of tools run on the same contract together.
        from datetime import timedelta
        start_window = latest.audit_date - timedelta(minutes=15)
        batch_audits = AuditHistory.query.filter(
            AuditHistory.filename == latest.filename,
            AuditHistory.audit_date >= start_window,
            AuditHistory.audit_date <= latest.audit_date
        ).all()

        state["model_name"]    = latest.filename
        state["active_tool"]   = latest.tool_used
        state["active_status"] = latest.status
        state["states_stored"] = latest.states_explored
        state["transitions"]   = latest.transitions
        state["depth"]         = latest.depth_reached
        state["datetime"]      = latest.audit_date.strftime("%Y-%m-%d %H:%M:%S")
        state["latest_audit_id"] = latest.id
        
        # 3. Aggregate tool results for the grid and top-level keys for JS compat
        all_ltl_results = []
        for audit in batch_audits:
            t_key = audit.tool_used.lower()
            # Determine progress based on status
            progress = 0
            status = (audit.status or "PENDING").upper()
            if status in ("PASS", "FAIL", "SUCCESS", "COMPLETED"):
                progress = 100
                status = "PASS" if status in ("PASS", "SUCCESS") else "FAIL"
            elif status in ("RUNNING", "PENDING"):
                progress = 50 # Default middle progress for active runs
                status = "RUNNING"
            
            # Populate state[tool] for the frontend JS to pick up
            state[t_key] = {
                "status": status,
                "timestamp": audit.audit_date.isoformat() if audit.audit_date else "",
                "progress": progress
            }
            
            # Merge LTL properties from all tools in the batch
            if audit.ltl_properties:
                try:
                    props = json.loads(audit.ltl_properties)
                    if isinstance(props, list):
                        existing_names = {p.get("name") for p in all_ltl_results}
                        for p in props:
                            if p.get("name") not in existing_names:
                                all_ltl_results.append(p)
                except Exception: pass

        state["ltl_results"] = all_ltl_results
        # Overall success: only if all tools in the batch passed
        state["success"] = all(a.status == "PASS" for a in batch_audits)
    else:
        # If no audit in DB, fallback to global state fields for active status
        state["active_status"] = state.get("active_status", "No runs yet")
        state["success"] = state.get("success", None)
        state["model_name"] = state.get("model_name", "No file loaded")

    return jsonify(state)

@api_v1.route("/state/current")
def api_state_current():
    """Returns global state enriched with DB aggregates for web-portal runs."""
    state = load_state()
    try:
        latest = AuditHistory.query.order_by(AuditHistory.audit_date.desc()).first()
        if latest:
            if not state.get("states_stored") and latest.states_explored:
                state["states_stored"] = latest.states_explored
            if not state.get("transitions") and latest.transitions:
                state["transitions"] = latest.transitions
            if not state.get("depth") and latest.depth_reached:
                state["depth"] = latest.depth_reached
            if not state.get("model_name") and latest.filename:
                state["model_name"] = latest.filename
            if not state.get("datetime") and latest.audit_date:
                state["datetime"] = latest.audit_date.strftime("%Y-%m-%d %H:%M:%S")
        if not state.get("ltl_results"):
            spin_row = AuditHistory.query.filter(
                AuditHistory.tool_used.ilike("SPIN")
            ).order_by(AuditHistory.audit_date.desc()).first()
            if spin_row and spin_row.ltl_properties:
                try:
                    import json as _j, re as _r
                    props = _j.loads(spin_row.ltl_properties)
                    if isinstance(props, list):
                        state["ltl_results"] = props
                    elif isinstance(props, str) and "ltl" in props:
                        names = _r.findall(r"ltl\s+(\w+)\s*\{", props)
                        state["ltl_results"] = [{"name":n,"formula":"","success":None,"status":"UNKNOWN"} for n in names]
                except Exception:
                    pass
    except Exception:
        pass
    return jsonify(state)



@api_v1.route("/sync-audit", methods=["POST"])
def api_sync_audit():
    # ── Secure Sync Token Check ─────────────────────────────────────────────
    # This allows the local desktop instance to push data to the remote portal
    sync_token = os.environ.get("SYNC_TOKEN")
    provided_token = request.headers.get("X-Sync-Token")
    
    # If a valid sync token is provided, bypass standard login check and process payload
    if sync_token and provided_token == sync_token:
        try:
            payload = request.get_json()
            if not payload or ("jobs" not in payload and "users" not in payload):
                return jsonify({"status": "error", "message": "Invalid sync payload"}), 400
            
            n = sync_audit_log(
                audit_jobs=payload.get("jobs"),
                users=payload.get("users")
            )
            return jsonify({"status": "success", "new_records": n})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── Manual Login Check (for UI button) ──────────────────────────────────
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized", "message": "Login required or invalid SYNC_TOKEN"}), 401

    # ── Default Sync Behavior ───────────────────────────────────────────────
    # If REMOTE_AUDIT_SYNC is enabled, automatically sync from the Render instance.
    # This makes the UI sync button work for cross-instance real-time updates.
    if os.environ.get("REMOTE_AUDIT_SYNC", "").lower() in ("1", "true", "yes", "on"):
        try:
            return api_sync_audit_remote()
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    n = sync_audit_log()
    return jsonify({"status": "success", "new_records": n})



@api_v1.route("/audit-log/raw")
def api_audit_log_raw():
    """Serve the remote desktop audit log JSON so other instances can sync."""
    try:
        if not AUDIT_LOG_FILE.exists():
            return jsonify({"error": "audit_log.json not found"}), 404
        return Response(AUDIT_LOG_FILE.read_text(encoding="utf-8"), mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Streamlit Control ─────────────────────────────────────────────────────────
_streamlit_proc = None

@api_v1.route("/streamlit/start")
@login_required
def streamlit_start():
    global _streamlit_proc
    if getattr(current_user, 'role', 'user') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    if _streamlit_proc and _streamlit_proc.poll() is None:
        return jsonify({"status": "already_running"})
    
    try:
        # root app.py is PROJECT_DIR / "app.py"
        cmd = [sys.executable, "-m", "streamlit", "run", str(PROJECT_DIR / "app.py"), 
               "--server.port", "8501", "--server.address", "0.0.0.0", "--server.headless", "true"]
        _streamlit_proc = subprocess.Popen(cmd, cwd=str(PROJECT_DIR))
        return jsonify({"status": "starting"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_v1.route("/streamlit/stop")
@login_required
def streamlit_stop():
    global _streamlit_proc
    if getattr(current_user, 'role', 'user') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    if _streamlit_proc:
        _streamlit_proc.terminate()
        _streamlit_proc = None
    return jsonify({"status": "stopped"})

@api_v1.route("/streamlit/status")
@login_required
def streamlit_status():
    global _streamlit_proc
    running = _streamlit_proc is not None and _streamlit_proc.poll() is None
    return jsonify({"running": running})


@api_v1.route("/sync-audit-remote", methods=["POST"])
@login_required
def api_sync_audit_remote():
    """Download audit_log.json from the Render instance and import into local DB."""
    try:
        render_base = os.environ.get("RENDER_BASE_URL")
        if not render_base:
            return jsonify({"error": "RENDER_BASE_URL env var not set"}), 400

        url = render_base.rstrip('/') + "/api/v1/audit-log/raw"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        audit_jobs = resp.json()
        if not isinstance(audit_jobs, list):
            return jsonify({"error": "remote audit log is not a JSON list"}), 400

        n = sync_audit_log(audit_jobs=audit_jobs)
        return jsonify({"status": "success", "new_records": n})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"remote fetch failed: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_v1.route("/set-theme", methods=["POST"])
def api_set_theme():
    theme = (request.get_json() or {}).get("theme", "dark")
    session["theme"] = theme
    return jsonify({"status": "success", "theme": theme})

@api_v1.route("/counterexample/runs")
@login_required
def api_counterexample_runs():
    rows = AuditHistory.query.filter(
        (AuditHistory.user_id == current_user.id) | (AuditHistory.user_id == None)
    ).order_by(AuditHistory.audit_date.desc()).limit(200).all()

    return jsonify([{
        "id":       r.id,
        "tool":     r.tool_used or "?",
        "filename": r.filename or "unknown",
        "status":   r.status or "?",
        "date":     r.audit_date.isoformat()[:16] if r.audit_date else "",
        "is_spin":  (r.tool_used or "").upper() == "SPIN",
    } for r in rows])

@api_v1.route("/run", methods=["POST"])
@login_required
def api_run():
    tool = request.form.get("tool", "SPIN").upper()
    filename = request.form.get("filename", "contract")
    spec_text = request.form.get("spec_text", "")
    code = request.form.get("code", "")

    # ── Reset Global State for a Fresh Run ──────────────────────────────────
    # This prevents old "FAIL" or "PASS" statuses from appearing in the UI
    state = load_state()
    TOOLS = ["spin", "coq", "lean", "certora", "kani", "prusti", "creusot", "verus"]
    for t in TOOLS:
        if t not in state:
            state[t] = {}
        state[t]["status"] = "Not run"
        state[t]["progress"] = 0
        state[t]["success"] = None
    state["active_tool"] = tool
    state["active_status"] = "PENDING"
    state["model_name"] = filename
    state["success"] = None
    state["ltl_results"] = []
    save_state(state)

    # Handle file uploads
    contract_content = code
    if "file" in request.files:
        f = request.files["file"]
        if f and f.filename:
            contract_content = f.read().decode("utf-8")
            filename = f.filename

    # Create pending audit record
    audit = AuditHistory(
        user_id=current_user.id,
        filename=filename,
        file_type=os.path.splitext(filename)[1] or ".sol",
        tool_used=tool,
        status="PENDING",
        verification_output="Verification queued...",
        source_code=contract_content[:50000] if contract_content else None,
    )
    db.session.add(audit)
    db.session.commit()

    # Trigger Celery task (preferred); fall back to SQLite queue worker
    task = None
    try:
        current_app.logger.info(f"Triggering verification task for audit {audit.id} using tool {tool}")
        task = run_verification_task.delay(
            audit.id,
            tool,
            filename,
            contract_content,
            spec_text,
            _get_verif_url(),
            _get_verif_headers()
        )
        current_app.logger.info(f"Task {task.id} queued successfully")
    except Exception as celery_err:
        current_app.logger.error(f"Celery failed ({celery_err}); falling back to SQLite queue worker.")
        # ── Fallback: submit directly to the SQLite queue ────────────────────
        try:
            from queue_manager import submit_job
            job_id = f"q-{audit.id}-{int(time.time())}"
            job_dir = os.path.join(
                current_app.config["UPLOAD_FOLDER"], f"job-{audit.id}"
            )
            os.makedirs(job_dir, exist_ok=True)

            # Persist the contract text so the worker can find it
            ext = os.path.splitext(filename)[1] or ".pml"
            contract_path = os.path.join(job_dir, f"contract{ext}")
            with open(contract_path, "w", encoding="utf-8") as _cf:
                _cf.write(contract_content)

            # Persist the spec text if provided
            spec_path = None
            if spec_text:
                spec_path = os.path.join(job_dir, "spec.txt")
                with open(spec_path, "w", encoding="utf-8") as _sf:
                    _sf.write(spec_text)

            submit_job(
                job_id=job_id,
                tool=tool.lower(),
                contract_path=contract_path,
                spec_path=spec_path,
                output_dir=job_dir,
            )
            audit.job_id = job_id
            db.session.commit()

            # Kick the queue-worker if it is not already running
            _ensure_worker_running(current_app)

            current_app.logger.info(f"Fallback queued job {job_id} in SQLite queue.")
        except Exception as fallback_err:
            current_app.logger.error(f"Fallback queue submission also failed: {fallback_err}")
            db.session.rollback()
            return jsonify({
                "status": "error",
                "message": f"Both Celery and fallback queue failed: {str(fallback_err)}"
            }), 500

    return jsonify({
        "status": "accepted",
        "audit_id": audit.id,
        "job_id": audit.id,
        "task_id": task.id if task else f"fallback-{audit.id}",
    })


def _ensure_worker_running(app):
    """Start the verification_worker.py if it is not already running."""
    import psutil
    WORKER_SCRIPT = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "verification_worker.py"
    )
    def _is_worker(p):
        try:
            cmd = " ".join(p.cmdline() or [])
            return "verification_worker.py" in cmd and p.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    running = any(_is_worker(p) for p in psutil.process_iter(["pid", "cmdline", "status"]))
    if not running:
        try:
            subprocess.Popen(
                [sys.executable, WORKER_SCRIPT],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            app.logger.info("Started verification_worker.py as fallback worker.")
        except Exception as e:
            app.logger.warning(f"Could not start fallback worker: {e}")

@api_v1.route("/job/<job_id>")
@login_required
def api_job_status(job_id):
    # Try to find by Audit ID first (for Celery-based runs)
    try:
        audit = AuditHistory.query.get(int(job_id))
        if audit:
            # Map AuditHistory status to frontend-expected status
            status_map = {
                "PENDING": "running",
                "RUNNING": "running",
                "PASS": "completed",
                "FAIL": "completed",
                "ERROR": "failed"
            }
            return jsonify({
                "status": status_map.get(audit.status, "running"),
                "result": {
                    "counterexample_found": audit.status == "FAIL",
                    "stdout": audit.verification_output
                }
            })
    except (ValueError, TypeError):
        # job_id was not an integer audit id
        # For the web new-run UI, return a JSON running payload instead of proxying.
        return jsonify({"status": "running", "result": {}})

    # If no AuditHistory row exists for this audit id, don't proxy to the
    # verification server (it can return HTML on errors/404). Return JSON.
    if not audit:
        return jsonify({"status": "running", "result": {}})

    # Fallback to proxying to the verification server
    verif_url = _get_verif_url()
    try:
        resp = requests.get(f"{verif_url}/job/{job_id}", headers=_get_verif_headers(), timeout=10)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_v1.route("/artifact/<job_id>/<filename>")
@login_required
def api_download_artifact(job_id, filename):
    verif_url = _get_verif_url()
    try:
        resp = requests.get(f"{verif_url}/download/{job_id}/{filename}", headers=_get_verif_headers(), stream=True, timeout=30)
        resp.raise_for_status()
        return Response(
            resp.iter_content(chunk_size=8192),
            content_type=resp.headers.get('Content-Type'),
            headers={"Content-Disposition": resp.headers.get('Content-Disposition', f'attachment; filename={filename}')}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_v1.route("/upload", methods=["POST"])
@login_required
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400
    fname = secure_filename(f.filename)
    dest  = os.path.join(current_app.config["UPLOAD_FOLDER"], fname)
    f.save(dest)
    return jsonify({"status": "ok", "filename": fname, "path": dest})

@api_v1.route("/generate-spec", methods=["POST"])
@login_required
def api_generate_spec():
    data     = request.get_json() or {}
    prompt   = data.get("prompt", "").strip()
    tool     = data.get("tool", "LTL").upper()
    contract = data.get("contract", "")
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400
    from llm_spec import generate
    result = generate(prompt, tool, contract)
    return jsonify(result)

@api_v1.route("/specs", methods=["GET"])
@login_required
def api_list_specs():
    specs_dir = PROJECT_DIR / "generated" / "specs"
    if not specs_dir.exists(): return jsonify([])
    specs = [{"name": f.name, "path": str(f)} for f in specs_dir.iterdir() if f.suffix in ('.spec', '.txt', '.cvl')]
    return jsonify(specs)

@api_v1.route("/log-content")
@login_required
def api_log_content():
    path = request.args.get("path", "")
    if not path:
        return jsonify({"error": "No path provided"}), 400
    
    # Handle DB virtual logs
    if path.startswith("db://"):
        try:
            audit_id = int(path.replace("db://", ""))
            audit = AuditHistory.query.get(audit_id)
            if not audit:
                return jsonify({"error": "Log not found in DB"}), 404
            
            content = audit.verification_output or ""
            # Use the full path resolution logic that includes DB fallback
            resolved = _load_verification_content(content, audit.report_path or "", audit_id=audit_id)
            return jsonify({"content": resolved})
        except Exception as e:
            return jsonify({"error": f"DB error: {str(e)}"}), 500
    
    # Handle physical file logs
    content = _load_verification_content(path)
    if content == path and not os.path.exists(path):
        return jsonify({"error": "File not found or could not be resolved"}), 404
    
    # Security check: ensure the resolved path is within PROJECT_DIR if it was a file
    if os.path.exists(path):
        abs_p = os.path.abspath(path)
        if not abs_p.startswith(str(PROJECT_DIR.resolve())):
              # Allow if it's in /tmp or something common if needed, but for now stick to project
              if not abs_p.startswith("/tmp"):
                  return jsonify({"error": "Access denied"}), 403
    
    return jsonify({"content": content[:100000]}) # Limit to 100k for browser performance

def _build_counterexample_payload(row, audit_id_label):
    """
    Shared helper that builds a complete counterexample JSON payload for any
    audit row, regardless of tool or whether the original log files are on disk.

    Strategy per tool:
    - SPIN: parse LTL rules + trace steps from log content or trail file.
    - All other tools: parse log content; if content is empty/unavailable,
      synthesise rules from ltl_properties column and generate a meaningful
      synthetic state diagram so the UI is never blank.
    """
    tool = (row.tool_used or "SPIN").upper()

    # ── 1. Load log content (handles path→content, DB fallback, etc.) ─────
    log_content = _load_verification_content(
        row.verification_output or "",
        row.report_path or "",
        audit_id=row.id,
    )

    # ── 2. Also try stored trace_data JSON (from worker) ─────────────────
    stored_trace = None
    if row.trace_data:
        try:
            stored_trace = json.loads(row.trace_data)
        except Exception:
            pass

    # ── 3. Get parser ─────────────────────────────────────────────────────
    try:
        parser = get_parser(tool)
    except Exception:
        parser = None

    # ── 4. Parse rules ────────────────────────────────────────────────────
    rules = []
    if parser:
        try:
            rules = parser.parse_rules(log_content)
        except Exception as e:
            current_app.logger.warning(f"parse_rules failed for {tool}: {e}")

    # Fallback: derive rules from ltl_properties column (stored by sync_audit_log)
    if not rules and row.ltl_properties:
        try:
            raw_ltl = row.ltl_properties
            # ltl_properties may be stored as JSON list or raw LTL text
            if raw_ltl.strip().startswith("["):
                ltl_list = json.loads(raw_ltl)
                for item in ltl_list:
                    if isinstance(item, dict):
                        status = "VERIFIED" if item.get("success") or item.get("status") == "VERIFIED" else \
                                 ("UNKNOWN" if item.get("errors", 0) == -1 else "VIOLATED")
                        rules.append({
                            "name": item.get("name", "property"),
                            "status": status,
                            "formula": item.get("formula", ""),
                            "category": _property_category(item.get("formula", "") or item.get("name", "")),
                            "errors": item.get("errors", 0),
                        })
            else:
                # Raw LTL text — extract formula names
                import re as _re
                for m in _re.finditer(r"ltl\s+(\w+)\s*\{([^}]+)\}", raw_ltl):
                    rules.append({
                        "name": m.group(1),
                        "status": "UNKNOWN",
                        "formula": m.group(2).strip(),
                        "category": _property_category(m.group(2)),
                        "errors": 0,
                    })
        except Exception:
            pass

    # Ultimate fallback: at least one rule so the panel is never empty
    if not rules:
        overall_status = (row.status or "FAIL").upper()
        rules = [{
            "name": f"{tool.lower()}_verification",
            "status": "VERIFIED" if overall_status == "PASS" else "VIOLATED",
            "formula": "",
            "category": "SAFETY",
            "errors": 0 if overall_status == "PASS" else 1,
        }]

    # ── 5. Parse trace ────────────────────────────────────────────────────
    trace_dict = {"steps": [], "final_variables": {}, "error_message": "", "tool": tool, "warnings": []}
    if stored_trace and stored_trace.get("steps"):
        # Use worker-persisted trace (most accurate)
        trace_dict = stored_trace
    elif parser:
        try:
            trace = parser.parse_trace(log_content, row.report_path or "")
            if trace:
                trace_dict = trace.to_dict()
        except Exception as e:
            current_app.logger.warning(f"parse_trace failed for {tool}: {e}")

    # ── 6. Synthetic trace when none available (simulated runs) ──────────
    if not trace_dict.get("steps") and log_content:
        # Extract any variable assignments and log lines to create pseudo-steps
        import re as _re
        steps = []
        current_vars = {}
        for i, line in enumerate(log_content.splitlines()[:200]):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            var_updates = {}
            for vm in _re.finditer(r"\b([A-Za-z_]\w*)\s*[=:]\s*([-\d]+|true|false|0x[0-9a-fA-F]+)\b", line):
                var_updates[vm.group(1)] = vm.group(2)
            prev = dict(current_vars)
            current_vars.update(var_updates)
            is_err = bool(_re.search(r"error|fail|violat|assert|panic", line, _re.IGNORECASE))
            steps.append({
                "step": i + 1, "step_number": i + 1,
                "proc": tool.lower(), "line": 0, "file": "", "source": "",
                "state": f"S{i}", "action": line[:200],
                "variables": dict(current_vars),
                "variables_before": prev,
                "variables_after": dict(current_vars),
                "updates": var_updates,
                "is_error": is_err,
            })
        if steps:
            trace_dict["steps"] = steps
            trace_dict["final_variables"] = current_vars
            if any(s["is_error"] for s in steps):
                trace_dict["error_message"] = "Property violation or error detected."

    # ── 7. State graph ────────────────────────────────────────────────────
    state_graph = None
    # a) Job-specific graph file (written by verification_worker)
    if row.job_id:
        for base in [
            PROJECT_DIR / "web_portal" / "verification_results" / row.job_id / "state_graph.json",
            PROJECT_DIR / "generated" / "jobs" / row.job_id / "state_graph.json",
        ]:
            if base.exists():
                try:
                    state_graph = json.loads(base.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass

    # b) Global fallback graph
    if not state_graph:
        state_graph = _load_state_graph()

    # c) Synthesise from trace steps when nothing else is available
    if not state_graph or not state_graph.get("nodes"):
        steps = trace_dict.get("steps", [])
        if steps:
            nodes, edges, seen = [], [], set()
            for i, s in enumerate(steps):
                sid = s.get("state") or f"S{i}"
                if sid not in seen:
                    nodes.append({
                        "id": sid,
                        "label": s.get("action", sid)[:30],
                        "type": "error" if s.get("is_error") else ("initial" if i == 0 else "normal"),
                    })
                    seen.add(sid)
                if i > 0:
                    prev_sid = steps[i - 1].get("state") or f"S{i-1}"
                    edges.append({"from": prev_sid, "to": sid, "label": s.get("action", "")[:20]})
            state_graph = {"nodes": nodes, "edges": edges}
        else:
            # Minimal FSM for lending pool (always visible)
            state_graph = {
                "nodes": [
                    {"id": "Idle",          "label": "Idle",          "type": "initial"},
                    {"id": "Collateralized","label": "Collateralized", "type": "normal"},
                    {"id": "DebtActive",    "label": "Debt Active",   "type": "normal"},
                    {"id": "Repaid",        "label": "Repaid",        "type": "normal"},
                    {"id": "Error",         "label": "Violation",     "type": "error"},
                ],
                "edges": [
                    {"from": "Idle",           "to": "Collateralized", "label": "deposit()"},
                    {"from": "Collateralized", "to": "DebtActive",     "label": "borrow()"},
                    {"from": "DebtActive",     "to": "Repaid",         "label": "repay()"},
                    {"from": "Repaid",         "to": "Idle",           "label": "withdraw()"},
                    {"from": "DebtActive",     "to": "Error",          "label": "debt > collateral"},
                ],
            }

    # ── 8. Recommendations ────────────────────────────────────────────────
    recs = []
    if parser:
        try:
            recs = parser.get_recommendations(row.status or "FAIL", log_content)
        except Exception:
            recs = []
    if not recs:
        overall = (row.status or "FAIL").upper()
        if overall == "PASS":
            recs = [f"All {tool} properties verified successfully."]
        else:
            recs = [
                f"{tool} found a property violation. Review the trace and variable state.",
                "Inspect variable values at each step to identify the root cause.",
                "Consider adding stronger preconditions or fixing the contract logic.",
            ]

    # ── 9. Assemble response ──────────────────────────────────────────────
    return {
        "audit_id": audit_id_label,
        "tool": tool,
        "status": row.status or "FAIL",
        "filename": row.filename or "unknown",
        "ltl_properties": rules,
        "trace_data": trace_dict,
        "recommendations": recs,
        "state_graph": state_graph,
        "source_code": row.source_code or "",
        "output": log_content[:3000] if log_content else "",
        "job_id": row.job_id or "",
        "stats": {
            "states":      row.states_explored or 0,
            "transitions": row.transitions or 0,
            "depth":       row.depth_reached or 0,
        },
    }


@api_v1.route("/counterexample/latest")
@login_required
def api_counterexample_latest():
    try:
        u_id = current_user.get_id()
        user_id = int(u_id) if u_id else None

        latest_row = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
        ).order_by(AuditHistory.audit_date.desc()).first()

        if latest_row and latest_row.tool_used:
            payload = _build_counterexample_payload(latest_row, latest_row.id)
            return jsonify(payload)

    except Exception as e:
        current_app.logger.error(f"Counterexample latest error: {e}", exc_info=True)

    # Default: global verification_state.json fallback
    state = load_state()
    spin_output = state.get("output", "")
    trace_steps, _ = _parse_spin_output_to_steps(spin_output)
    return jsonify({
        "audit_id": "latest",
        "tool": "SPIN",
        "status": "PASS" if state.get("success") else "FAIL",
        "filename": state.get("model_name", "unknown"),
        "ltl_properties": [],
        "trace_data": {"steps": trace_steps},
        "recommendations": _spin_recs(state.get("success", True), trace_steps, spin_output),
        "state_graph": _load_state_graph(),
        "source_code": "",
        "output": spin_output[:3000],
        "job_id": "",
        "stats": {"states": 0, "transitions": 0, "depth": 0},
    })


@api_v1.route("/counterexample/<audit_id>")
@login_required
def api_counterexample(audit_id):
    if audit_id == "latest":
        return api_counterexample_latest()

    try:
        audit_id_int = int(audit_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid audit ID"}), 400

    u_id = current_user.get_id()
    user_id = int(u_id) if u_id else None

    row = AuditHistory.query.filter_by(id=audit_id_int).filter(
        (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
    ).first()

    if not row:
        return jsonify({"error": "Not found"}), 404

    try:
        payload = _build_counterexample_payload(row, audit_id)
        return jsonify(payload)
    except Exception as e:
        current_app.logger.error(f"Counterexample error for audit {audit_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_v1.route("/desktop-runs")
@login_required
def api_desktop_runs():
    rows = AuditHistory.query.filter(
        (AuditHistory.user_id == current_user.id) | (AuditHistory.user_id == None)
    ).order_by(AuditHistory.audit_date.desc()).limit(50).all()
    
    return jsonify([{
        "id":        r.id,
        "timestamp": r.audit_date.isoformat() if r.audit_date else "",
        "tool":      r.tool_used or "",
        "file":      r.filename or "",
        "status":    r.status or "",
        "states":    r.states_explored or 0,
        "depth":     r.depth_reached or 0,
        "error_msg": r.vulnerabilities_found or "",
    } for r in rows])

@api_v1.route("/trace/<audit_id>")
@login_required
def api_trace(audit_id):
    if audit_id == "latest":
        row = AuditHistory.query.filter(
            (AuditHistory.user_id == current_user.id) | (AuditHistory.user_id == None)
        ).order_by(AuditHistory.audit_date.desc()).first()
    else:
        try:
            row = AuditHistory.query.filter_by(id=int(audit_id)).filter(
                (AuditHistory.user_id == current_user.id) | (AuditHistory.user_id == None)
            ).first()
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid audit ID"}), 400

    if not row: return jsonify({"error": "Not found"}), 404

    from trace_parsers import get_parser
    parser = get_parser(row.tool_used)
    if parser:
        log_content = _load_verification_content(
            row.verification_output or "",
            row.report_path or "",
            audit_id=row.id,
        )
        trace = parser.parse_trace(log_content, row.report_path or "")
        steps = [s.to_dict() for s in (trace.steps if trace else [])]
        return jsonify({
            # "steps" is what trace.js expects; "trace" kept for back-compat
            "steps":           steps,
            "trace":           steps,
            "final_variables": trace.final_variables if trace else {},
            "error_message":   trace.error_message if trace else None,
            "tool":            row.tool_used,
            "warnings":        trace.warnings if trace else [],
        })
    return jsonify({"error": "Parser failed", "steps": [], "trace": []}), 500

@api_v1.route("/state-graph/<audit_id>")
def api_state_graph(audit_id):
    # "latest" → resolve to the most recent audit for the current user
    if audit_id == "latest":
        try:
            u_id = current_user.get_id() if current_user.is_authenticated else None
            user_id = int(u_id) if u_id else None
            row = AuditHistory.query.filter(
                (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
            ).order_by(AuditHistory.audit_date.desc()).first()
            if row:
                audit_id = str(row.id)
        except Exception:
            pass

    # Try specific audit first
    if audit_id and audit_id not in ("0", "latest"):
        try:
            audit = AuditHistory.query.get(int(audit_id))
            if audit and audit.job_id:
                job_graph = PROJECT_DIR / "web_portal" / "verification_results" / audit.job_id / "state_graph.json"
                if job_graph.exists():
                    try:
                        return jsonify(json.loads(job_graph.read_text(encoding="utf-8")))
                    except Exception:
                        pass
        except (ValueError, TypeError):
            pass

    sg = _load_state_graph()
    return jsonify(sg) if sg else (jsonify({"error": "Not found"}), 404)


@api_v1.route("/visualization/current")
def api_visualization_current():
    """
    Return the filename and audit_id for the visualization page so it can
    display the correct contract name and fetch the right state graph,
    instead of always falling back to the stale verification_state.json.
    """
    try:
        u_id = current_user.get_id() if current_user.is_authenticated else None
        user_id = int(u_id) if u_id else None
        row = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
        ).order_by(AuditHistory.audit_date.desc()).first()
        if row:
            return jsonify({
                "model_name": row.filename or "",
                "audit_id":   row.id,
                "tool":       row.tool_used or "",
                "status":     row.status or "",
            })
    except Exception:
        pass

    # Fallback to global state
    state = load_state()
    return jsonify({
        "model_name": state.get("model_name", ""),
        "audit_id":   "latest",
        "tool":       state.get("active_tool", ""),
        "status":     state.get("active_status", ""),
    })

@api_v1.route("/ltl-properties")
def api_ltl_properties():
    state = load_state()
    return jsonify(state.get("ltl_results", []))

def _check_tool_available(tool: str) -> bool:
    """
    Return True if the tool binary is reachable.
    Some tools (Kani, Prusti, Creusot) are cargo sub-commands, not standalone
    binaries, so `shutil.which('cargo-kani')` fails even when installed.
    We try the canonical binary name first, then fall back to a quick
    subprocess probe so the Tools page reflects reality.
    """
    # Primary binary names
    PRIMARY = {
        "SPIN":    ["spin"],
        "COQ":     ["coqc"],
        "LEAN":    ["lean"],
        "CERTORA": ["certoraRun", "certora"],
        "KANI":    ["cargo-kani", "kani"],
        "PRUSTI":  ["prusti-rustc", "cargo-prusti"],
        "CREUSOT": ["cargo-creusot", "creusot"],
        "VERUS":   ["verus"],
    }
    # Fallback subprocess probes (used when shutil.which misses cargo sub-cmds)
    PROBE_CMDS = {
        "KANI":    ["cargo", "kani", "--version"],
        "PRUSTI":  ["cargo", "prusti", "--version"],
        "CREUSOT": ["cargo", "creusot", "--version"],
    }

    for binary in PRIMARY.get(tool, []):
        if shutil.which(binary):
            return True

    if tool in PROBE_CMDS:
        try:
            r = subprocess.run(
                PROBE_CMDS[tool],
                capture_output=True, timeout=5,
                env={**os.environ, "PATH": os.environ.get("PATH", "")}
            )
            if r.returncode == 0:
                return True
        except Exception:
            pass

    return False


@api_v1.route("/tools/status")
def api_tools_status():
    """Per-tool status merged from PATH check + DB last-known status."""
    state = load_state()
    TOOLS = ["SPIN", "COQ", "LEAN", "CERTORA", "KANI", "PRUSTI", "CREUSOT", "VERUS"]
    try:
        from web_portal.verification_simulator import simulate as _sim  # noqa
        has_simulator = True
    except Exception:
        has_simulator = False

    db_status = {}
    try:
        for tool in TOOLS:
            row = AuditHistory.query.filter(
                AuditHistory.tool_used.ilike(tool)
            ).order_by(AuditHistory.audit_date.desc()).first()
            if row:
                db_status[tool] = {
                    "status":   (row.status or "UNKNOWN").upper(),
                    "last_run": row.audit_date.isoformat() if row.audit_date else "",
                    "filename": row.filename or "",
                    "source":   "web_portal" if row.user_id else "desktop",
                }
    except Exception:
        pass

    result = {}
    for tool in TOOLS:
        available  = _check_tool_available(tool)
        tool_data  = state.get(tool.lower(), {})
        db_info    = db_status.get(tool, {})
        json_status = tool_data.get("status", "")
        db_stat     = db_info.get("status", "UNKNOWN")
        last_status = json_status if json_status else db_stat
        last_run    = tool_data.get("timestamp") or db_info.get("last_run", "")
        result[tool] = {
            "available":   available,
            "status":      last_status,
            "last_status": last_status,
            "last_run":    last_run,
            "simulated":   not available,
            "has_db_data": bool(db_info),
            "filename":    db_info.get("filename", tool_data.get("model_name", "")),
            "source":      db_info.get("source", "desktop"),
        }
    return jsonify(result)


@api_v1.route("/save-spec", methods=["POST"])
@login_required
def api_save_spec():
    data = request.get_json() or {}
    ltl, cvl, name = data.get("ltl", ""), data.get("cvl", ""), data.get("name", "saved")
    safe_name = re.sub(r'[^A-Za-z0-9_\-\.]', '_', name)
    specs_dir = PROJECT_DIR / "generated" / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    
    if ltl: (specs_dir / f"{safe_name}.spec").write_text(ltl)
    if cvl: (specs_dir / f"{safe_name}.cvl").write_text(cvl)
    
    return jsonify({"status": "success"})

@api_v1.route("/specs/<name>", methods=["GET"])
@login_required
def api_get_spec(name):
    specs_dir = PROJECT_DIR / "generated" / "specs"
    spec_path = specs_dir / name
    if not spec_path.exists():
        return jsonify({"error": "Spec not found"}), 404
    try:
        content = spec_path.read_text(encoding="utf-8")
        return jsonify({"name": name, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_v1.route("/events/emit", methods=["POST"])
def api_emit_event():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    
    # Import socketio locally to avoid circular dependency
    from app import socketio
    
    # 1. Update global state for real-time dashboard sync
    state = load_state()
    tool = (data.get("tool") or "SPIN").lower()
    
    # Extract stats if available
    states = data.get("states_explored") or data.get("states") or state.get("states_stored", 0)
    trans = data.get("transitions") or state.get("transitions", 0)
    depth = data.get("depth_reached") or data.get("depth") or state.get("depth", 0)
    
    # Update tool-specific state
    state[tool] = {
        "status": data.get("status", "UNKNOWN"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model_name": data.get("filename", state.get("model_name", "unknown")),
        "success": data.get("status") in ["PASS", "VERIFIED"]
    }
    
    # Update global stats
    state["states_stored"] = states
    state["transitions"] = trans
    state["depth"] = depth
    state["model_name"] = data.get("filename", state.get("model_name", "unknown"))
    state["success"] = data.get("status") in ["PASS", "VERIFIED"]
    state["datetime"] = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # If it's a SPIN result with LTL, update ltl_results
    if "ltl_results" in data:
        state["ltl_results"] = data["ltl_results"]
    
    save_state(state)
    
    # 2. Emit events to connected clients
    socketio.emit("verification_complete", data)
    socketio.emit("verification_update", state)
    
    # 3. Sync DB
    sync_audit_log()
    
    return jsonify({"status": "success"})

@api_v1.route("/etherscan/fetch", methods=["POST"])
@login_required
def api_etherscan_fetch():
    address = request.json.get("address")
    network = request.json.get("network", "mainnet")
    api_key = current_app.config.get("ETHERSCAN_API_KEY")

    if not address:
        return jsonify({"error": "Address is required"}), 400
    if not api_key:
        return jsonify({"error": "Etherscan API key not configured"}), 500

    base_url = "https://api.etherscan.io/api"
    if network == "sepolia":
        base_url = "https://api-sepolia.etherscan.io/api"
    elif network == "goerli":
        base_url = "https://api-goerli.etherscan.io/api"

    params = {
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": api_key
    }

    try:
        resp = requests.get(base_url, params=params)
        data = resp.json()
        if data["status"] == "1" and data["result"]:
            result = data["result"][0]
            source = result.get("SourceCode", "")
            name = result.get("ContractName", "Contract")
            
            # Handle JSON-encoded multi-file sources
            if source.startswith("{{") and source.endswith("}}"):
                try:
                    source_json = json.loads(source[1:-1])
                    sources = source_json.get("sources", {})
                    source = ""
                    for path, content in sources.items():
                        source += f"// File: {path}\n{content['content']}\n\n"
                except: pass

            return jsonify({
                "status": "success",
                "source": source,
                "name": name,
                "compiler": result.get("CompilerVersion"),
                "address": address
            })
        else:
            return jsonify({"error": data.get("message", "Contract not found")}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# NEW ROUTES — added by apply_fixes.py
# ══════════════════════════════════════════════════════════════════════════════

@api_v1.route("/dashboard/summary")
@login_required
def api_dashboard_summary():
    """Holistic KPI data from DB — used when verification_state.json is absent."""
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None
    try:
        from sqlalchemy import func as _func
        base = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        )
        total  = base.count()
        pass_c = base.filter(AuditHistory.status.ilike("PASS")).count()
        fail_c = base.filter(AuditHistory.status.ilike("FAIL")).count()
        tools_q = db.session.query(_func.distinct(AuditHistory.tool_used)).filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).all()
        tools_used = [t[0] for t in tools_q if t[0]]
        latest = base.order_by(AuditHistory.audit_date.desc()).first()
        ltl_pass = ltl_fail = 0
        
        # Aggregate LTL results from the latest "batch" of audits
        if latest:
            from datetime import timedelta
            batch_window = latest.audit_date - timedelta(minutes=10)
            batch_audits = base.filter(
                AuditHistory.filename == latest.filename,
                AuditHistory.audit_date >= batch_window,
                AuditHistory.audit_date <= latest.audit_date
            ).all()
            
            seen_ltl = set()
            for audit in batch_audits:
                if audit.ltl_properties:
                    try:
                        props = json.loads(audit.ltl_properties)
                        if isinstance(props, list):
                            for p in props:
                                name = p.get("name")
                                if name and name not in seen_ltl:
                                    seen_ltl.add(name)
                                    if p.get("success") is True or p.get("status") == "VERIFIED": ltl_pass += 1
                                    elif p.get("success") is False or p.get("status") == "VIOLATED": ltl_fail += 1
                    except Exception: pass
        
        web_count     = base.filter(AuditHistory.user_id.isnot(None)).count()
        desktop_count = base.filter(AuditHistory.user_id.is_(None)).count()

        # Count actually available tools from the system
        TOOLS = ["SPIN", "COQ", "LEAN", "CERTORA", "KANI", "PRUSTI", "CREUSOT", "VERUS"]
        installed_count = sum(1 for t in TOOLS if _check_tool_available(t))

        return jsonify({
            "total_runs": total, "pass_runs": pass_c, "fail_runs": fail_c,
            "tools_used": tools_used, "tools_available": installed_count,
            "latest_states": latest.states_explored if latest else 0,
            "latest_trans":  latest.transitions     if latest else 0,
            "latest_depth":  latest.depth_reached   if latest else 0,
            "latest_tool":   latest.tool_used        if latest else "",
            "latest_file":   latest.filename         if latest else "",
            "latest_date":   latest.audit_date.strftime("%Y-%m-%d %H:%M:%S") if (latest and latest.audit_date) else "",
            "latest_audit_id": latest.id             if latest else None,
            "ltl_pass": ltl_pass, "ltl_fail": ltl_fail,
            "run_sources": {"web_portal": web_count, "desktop": desktop_count},
        })
    except Exception as e:
        return jsonify({"error": str(e), "total_runs": 0}), 500


@api_v1.route("/runs/recent")
@login_required
def api_recent_runs():
    """Unified run list (desktop + web-portal) with source tag and log preview."""
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None
    limit   = min(int(request.args.get("limit", 30)), 200)
    try:
        rows = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).order_by(AuditHistory.audit_date.desc()).limit(limit).all()
        result = []
        for r in rows:
            log_raw  = r.verification_output or ""
            preview  = log_raw[:300].strip() if log_raw else ""
            ltl_pass = ltl_fail = 0
            if r.ltl_properties:
                try:
                    props = json.loads(r.ltl_properties)
                    if isinstance(props, list):
                        for p in props:
                            if p.get("success") is True or p.get("status") == "VERIFIED": ltl_pass += 1
                            else: ltl_fail += 1
                except Exception: pass
            result.append({
                "id":          r.id,
                "timestamp":   r.audit_date.isoformat() if r.audit_date else "",
                "date_short":  r.audit_date.strftime("%Y-%m-%d %H:%M") if r.audit_date else "",
                "tool":        (r.tool_used or "").upper(),
                "file":        r.filename or "unknown",
                "status":      (r.status or "UNKNOWN").upper(),
                "states":      r.states_explored or 0,
                "transitions": r.transitions     or 0,
                "depth":       r.depth_reached   or 0,
                "error_msg":   r.vulnerabilities_found or "",
                "ltl_pass":    ltl_pass, "ltl_fail": ltl_fail,
                "log_preview": preview,
                "source":      "web_portal" if r.user_id else "desktop",
                "has_trace":   bool(r.report_path or r.trace_data),
                "audit_url":   f"/counterexample/{r.id}",
                "trace_url":   f"/trace/{r.id}",
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "runs": []}), 500


@api_v1.route("/log-view/<audit_id>")
@login_required
def api_log_view(audit_id):
    """Returns stored log content for a run — powers the Logs page modal."""
    try:
        u_id    = current_user.get_id()
        user_id = int(u_id) if u_id else None
        if audit_id.startswith("db://"):
            row_id = int(audit_id.replace("db://", ""))
        else:
            row_id = int(audit_id)
        row = AuditHistory.query.filter_by(id=row_id).filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).first()
        if not row:
            return jsonify({"error": "Not found"}), 404
        content = row.verification_output or ""
        if content and "\n" not in content and len(content) < 600:
            try:
                p = Path(content)
                if p.exists():
                    content = p.read_text(encoding="utf-8", errors="replace")[:100000]
            except Exception: pass
        ltl = []
        if row.ltl_properties:
            try:
                ltl = json.loads(row.ltl_properties)
                if not isinstance(ltl, list): ltl = []
            except Exception: pass
        return jsonify({
            "id": row.id, "tool": row.tool_used or "",
            "filename": row.filename or "", "status": row.status or "",
            "date": row.audit_date.strftime("%Y-%m-%d %H:%M:%S") if row.audit_date else "",
            "states": row.states_explored or 0, "depth": row.depth_reached or 0,
            "content": content, "ltl": ltl,
            "source": "web_portal" if row.user_id else "desktop",
        })
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid ID: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_v1.route("/log-download/<path:log_ref>")
@login_required
def api_log_download(log_ref):
    """Download verification log as a downloadable text file.
    Accepts either an audit ID (integer), a db:// ID, or a file path.
    """
    try:
        u_id    = current_user.get_id()
        user_id = int(u_id) if u_id else None
        
        # Strip db:// prefix if present
        if log_ref.startswith("db://"):
            log_ref = log_ref.replace("db://", "")
        
        # Try as audit ID first
        try:
            row_id = int(log_ref)
            row = AuditHistory.query.filter_by(id=row_id).filter(
                (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
            ).first()
            if row:
                content = row.verification_output or ""
                resolved = _load_verification_content(content, row.report_path or "", audit_id=row.id)
                if resolved and resolved != content:
                    content = resolved
                filename = row.filename or f"verification_log_{row.id}.txt"
                if not filename.endswith(".txt") and not "." in filename:
                    filename = filename + ".txt"
                return Response(
                    content,
                    mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
        except ValueError:
            pass
        
        # Treat as file path
        content = _load_verification_content(log_ref)
        if content == log_ref and not os.path.exists(log_ref):
            return jsonify({"error": "File not found"}), 404
        
        # Security check for file path
        if os.path.exists(log_ref):
            abs_p = os.path.abspath(log_ref)
            if not abs_p.startswith(str(PROJECT_DIR.resolve())):
                if not abs_p.startswith("/tmp"):
                    return jsonify({"error": "Access denied"}), 403
        
        filename = Path(log_ref).name
        return Response(
            content,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
