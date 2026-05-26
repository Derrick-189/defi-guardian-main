"""
DeFi Guardian — Web Portal v2
Unified Flask application: portal + Streamlit dashboard features combined.
Real-time data via SocketIO file-watcher + desktop event bridge.
"""
from __future__ import annotations

# ── Monkey Patching (Must be first) ──────────────────────────────────────────
import eventlet
eventlet.monkey_patch()

import os, sys
import json, re, time, threading, shutil
from datetime import datetime
from pathlib import Path

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, jsonify, send_from_directory)
from flask_login import (LoginManager, UserMixin, login_user,
                         login_required, logout_user, current_user)
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

from config import config_by_name
import logging
from logging.handlers import RotatingFileHandler

# ── Path setup ────────────────────────────────────────────────────────────────
PORTAL_DIR  = Path(__file__).parent
PROJECT_DIR = PORTAL_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

# Augment PATH for verification tools
def _augment_path():
    home = Path.home()
    extra_paths = [
        str(home / ".elan" / "bin"),
        str(home / ".cargo" / "bin"),
        str(home / ".opam" / "default" / "bin"),
        str(home / ".local" / "bin"),
        str(home / "Library/Python/3.9/bin"), # Common for Certora on macOS
        "/usr/local/bin",
        "/opt/verus",
    ]
    current_path = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in current_path:
            current_path = f"{p}{os.pathsep}{current_path}"
    os.environ["PATH"] = current_path

_augment_path()

AUDIT_LOG_FILE     = PROJECT_DIR / "generated" / "reports" / "audit_log.json"
VERIFICATION_STATE = PROJECT_DIR / "verification_state.json"
MODELS_DIR         = PROJECT_DIR / "generated" / "models"
LOGS_DIR           = PROJECT_DIR / "logs"
REPORTS_DIR        = PROJECT_DIR / "generated" / "reports"

# ── App setup ─────────────────────────────────────────────────────────────────
env = os.environ.get("FLASK_ENV", "dev")
app = Flask(__name__)
app.config.from_object(config_by_name[env])

# ── Logging Setup ─────────────────────────────────────────────────────────────
if not app.debug:
    if not LOGS_DIR.exists():
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(LOGS_DIR / 'defi_guardian.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('DeFi Guardian Startup')

SPECS_DIR = Path(app.config["PROJECT_DIR"]) / "generated" / "specs"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(SPECS_DIR, exist_ok=True)

# ── SocketIO Setup ────────────────────────────────────────────────────────────
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet",
                    logger=False, engineio_logger=False)

# Initialize Benchmark Runner
from benchmarks_runner import BenchmarkRunner
bench_runner = BenchmarkRunner(socketio)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

# ── DB bootstrap ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(PORTAL_DIR))   # so audit_db, llm_spec, etc. resolve
from web_portal.audit_db import db, User, AuditHistory, ContactMessage, init_db, sync_audit_log, get_user_audits, get_public_audits, seed_demo_data
from utils import _load_state_graph, _parse_spin_output_to_steps, _spin_recs
import llm_spec

# ── Automatic Migration (for Render Free Tier & Legacy Sync) ────────────────
def _auto_migrate():
    """Automatically migrate data to the active database on startup."""
    try:
        # 1. Legacy Streamlit DB -> SQLite Portal DB (or Postgres if set)
        legacy_db = PROJECT_DIR / "generated" / "reports" / "dashboard_users.db"
        if legacy_db.exists():
            print(f"Detected legacy Streamlit database at {legacy_db}. Syncing...")
            from migrate_sqlite_to_postgres import migrate_legacy_sqlite
            migrate_legacy_sqlite(legacy_db, app, db, User)
            # Rename legacy so we don't sync every time
            legacy_db.rename(legacy_db.with_suffix(".db.synced"))

        # 2. SQLite Portal DB -> Postgres (if DATABASE_URL is set)
        sqlite_path = Path(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        # If we are currently using Postgres, check if there's a local SQLite file to migrate
        if os.environ.get("DATABASE_URL") and sqlite_path.exists() and "sqlite" not in app.config["SQLALCHEMY_DATABASE_URI"]:
            print("Detected local SQLite database and DATABASE_URL. Starting auto-migration...")
            from migrate_sqlite_to_postgres import migrate
            migrate(app=app, db=db, User=User, AuditHistory=AuditHistory, ContactMessage=ContactMessage)
            sqlite_path.rename(sqlite_path.with_suffix(".db.migrated"))
            print("Auto-migration successful.")
    except Exception as e:
        app.logger.error(f"Auto-migration failed: {e}")
        print(f"Auto-migration failed: {e}")

with app.app_context():
    try:
        init_db(app)
        _auto_migrate()
        seed_demo_data()
        sync_audit_log()
    except Exception as e:
        app.logger.error(f"Database initialization failed: {e}")
        # If Postgres fails, you might want to force a fallback to SQLite here
        # but that requires re-configuring the app, which is complex at runtime.
        # For now, we'll just log it clearly.
        if "Connection refused" in str(e):
            print("\n" + "="*60)
            print("ERROR: Connection to PostgreSQL failed (Connection Refused).")
            print("If you are running locally, ensure Postgres is started or UNSET DATABASE_URL.")
            print("="*60 + "\n")
        raise e

# ── Blueprints ────────────────────────────────────────────────────────────────
from api_v1 import api_v1
app.register_blueprint(api_v1, url_prefix='/api/v1')

# ── Celery Setup ──────────────────────────────────────────────────────────────
from celery import Celery

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    # Strip old-style CELERY_* keys before merging, to keep config consistent
    _celery_ns = {k: v for k, v in app.config.items()
                  if not k.startswith('CELERY_')}
    celery.conf.update(_celery_ns)
    celery.conf.update(
        result_backend=app.config['CELERY_RESULT_BACKEND'],
        broker_url=app.config['CELERY_BROKER_URL'],
        broker_connection_retry=True,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=5,
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

celery_app = make_celery(app)
# Make celery_app available for shared_task
import tasks 

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_session():
    return db.session

def load_state() -> dict:
    if VERIFICATION_STATE.exists():
        try:
            return json.loads(VERIFICATION_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def load_audit_log(limit: int = 50) -> list:
    if AUDIT_LOG_FILE.exists():
        try:
            data = json.loads(AUDIT_LOG_FILE.read_text(encoding="utf-8"))
            return data[:limit]
        except Exception:
            pass
    return []

def _find_latest_log(tool: str) -> str:
    d = LOGS_DIR / tool.lower()
    if d.is_dir():
        files = sorted(d.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            return str(files[0])
    return ""

def _get_verif_url():
    env_url = os.environ.get("VERIFICATION_SERVER_URL")
    if env_url: return env_url
    host = request.headers.get("Host", "127.0.0.1")
    if any(local in host for local in ["localhost", "127.0.0.1"]):
        return "http://127.0.0.1:5005"
    return os.environ.get("REMOTE_VERIFICATION_URL", "http://127.0.0.1:9005")

# ── Background file-watcher ───────────────────────────────────────────────────
_last_mtime: float = 0.0

def _watch():
    global _last_mtime
    while True:
        try:
            if VERIFICATION_STATE.exists():
                mt = VERIFICATION_STATE.stat().st_mtime
                if mt != _last_mtime:
                    _last_mtime = mt
                    state = load_state()
                    with app.app_context():
                        sync_audit_log()
                    socketio.emit("verification_update", state)
        except Exception:
            pass
        eventlet.sleep(2)

eventlet.spawn(_watch)

# ── Context processor ─────────────────────────────────────────────────────────
@app.context_processor
def _globals():
    return {
        "current_year": datetime.now().year,
        "app_name":     "DeFi Guardian",
        "app_version":  "2.0.0",
        "theme":        session.get("theme", "dark"),
        "is_remote":    os.environ.get("REMOTE_VERIFICATION_URL") is not None,
        "verif_url":    _get_verif_url(),
    }

# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html", recent_audits=get_public_audits(5))

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/services")
def services():
    plans = [
        {"name": "Community", "price": 0, "featured": False,
         "features": ["SPIN Model Checking", "3 contracts/month", "8 LTL properties", "Community support"]},
        {"name": "Professional", "price": 49, "featured": True,
         "features": ["Full 8-tool suite", "Rust verification", "Coq & Lean proofs", "Priority support", "API access"]},
        {"name": "Enterprise", "price": -1, "featured": False,
         "features": ["Dedicated instance", "Custom integrations", "SLA guarantee", "On-premise", "Training"]},
    ]
    return render_template("services.html", plans=plans)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        msg = ContactMessage(
            name=request.form.get("name",""),
            email=request.form.get("email",""),
            subject=request.form.get("subject",""),
            message=request.form.get("message","")
        )
        db.session.add(msg)
        db.session.commit()
        flash("Message sent — we'll be in touch soon.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email    = request.form.get("email","").strip()
        password = request.form.get("password","")
        if not all([username, email, password]):
            flash("All fields are required.", "danger")
            return render_template("register.html")
        
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Username or email already taken.", "danger")
            return render_template("register.html")
        
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Account created — please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","")
        password = request.form.get("password","")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login = datetime.now()
            db.session.commit()
            flash(f"Welcome back, {username}!", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("index"))

# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATED ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    sync_audit_log()
    audits = get_user_audits(current_user.id)
    state  = load_state()
    return render_template("dashboard.html", audits=audits, state=state)

@app.route("/tools")
@login_required
def tools():
    state = load_state()
    return render_template("tools.html", state=state)

@app.route("/new-run")
def new_run():
    return render_template("new_run.html")

@app.route("/active")
@login_required
def active_verification():
    return render_template("active.html")

@app.route("/counterexample/latest")
def counterexample_latest():
    # Resolve "latest" to an actual audit row so the template gets real data
    audit = {}
    try:
        u_id = current_user.get_id() if current_user.is_authenticated else None
        user_id = int(u_id) if u_id else None
        row = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
        ).order_by(AuditHistory.audit_date.desc()).first()
        if row:
            audit = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    except Exception:
        pass
    return render_template("counterexample.html", audit_id=audit.get("id", "latest"), audit=audit)

@app.route("/trace/latest")
@login_required
def trace_latest():
    # Resolve "latest" to an actual audit row so the template shows the header
    audit = {}
    try:
        u_id = current_user.get_id()
        user_id = int(u_id) if u_id else None
        row = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
        ).order_by(AuditHistory.audit_date.desc()).first()
        if row:
            audit = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    except Exception:
        pass
    return render_template("trace.html", audit_id=audit.get("id", "latest"), audit=audit)

@app.route("/counterexample/<audit_id>")
@login_required
def counterexample_analysis(audit_id):
    # Support both int DB ids and string audit_log ids
    audit = {}
    try:
        u_id = current_user.get_id()
        user_id = int(u_id) if u_id else None
        row = AuditHistory.query.filter_by(id=int(audit_id)).filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
        ).first()
        if row:
            audit = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    except (ValueError, TypeError):
        pass
    return render_template("counterexample.html", audit_id=audit_id, audit=audit)

@app.route("/trace/<audit_id>")
@login_required
def trace_viewer(audit_id):
    audit = {}
    try:
        u_id = current_user.get_id()
        user_id = int(u_id) if u_id else None
        row = AuditHistory.query.filter_by(id=int(audit_id)).filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id == None)
        ).first()
        if row:
            audit = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    except (ValueError, TypeError):
        pass
    return render_template("trace.html", audit_id=audit_id, audit=audit)

@app.route("/visualization")
def visualization():
    return render_template("visualization.html")

@app.route("/specifications")
@login_required
def specifications():
    # Load current contract source for context
    sol_path = PROJECT_DIR / "SimpleLending.sol"
    contract_src = sol_path.read_text(encoding="utf-8") if sol_path.exists() else ""
    return render_template("specifications.html", contract_src=contract_src)

@app.route("/api/v1/benchmarks/run", methods=["POST"])
@login_required
def api_run_benchmarks():
    if bench_runner.is_running:
        return jsonify({"status": "already_running"}), 400
    
    bench_runner.run_all()
    return jsonify({"status": "started"})

@app.route("/benchmarks")
@login_required
def benchmarks():
    bench_file = PROJECT_DIR / "benchmarks" / "benchmark_results.json"
    raw = []
    if bench_file.exists():
        try:
            raw = json.loads(bench_file.read_text())
        except Exception:
            pass
    results = []
    for r in raw:
        results.append({
            "tool":     r.get("tool", r.get("name", "?")),
            "contract": r.get("contract", r.get("filename", r.get("file", "?"))),
            "time":     float(r.get("time_seconds", r.get("duration", r.get("time", 0))) or 0),
            "states":   int(r.get("states", r.get("states_explored", 0)) or 0),
            "rate":     float(r.get("success_rate", r.get("pass_rate",
                            100 if r.get("success") else 0)) or 0),
            "passed":   bool(r.get("passed", r.get("success",
                            str(r.get("status","")).upper() in ("PASS","SUCCESS","TRUE")))),
            "date":     str(r.get("date", r.get("timestamp", r.get("audit_date", ""))))[:16],
        })
    return render_template("benchmarks.html", results=results)

@app.route("/logs")
@login_required
def logs():
    entries = []
    log_to_contract = {}
    
    # 1. Map contracts from the JSON audit log
    try:
        audit_data = json.loads(AUDIT_LOG_FILE.read_text(encoding="utf-8"))
        for job in audit_data:
            lp, fn = job.get("log_path", ""), job.get("file", "")
            if lp and fn:
                log_to_contract[str(Path(lp).resolve())] = fn
    except Exception: pass

    # 2. Map contracts from DB audit history (for files that exist on disk)
    try:
        rows = AuditHistory.query.filter(AuditHistory.verification_output != '').all()
        for row in rows:
            lp, fn = row.verification_output or "", row.filename or ""
            if lp and fn:
                # If it's a path, resolve it. If it's content, we'll handle it below.
                try:
                    p = Path(lp)
                    if p.exists():
                        log_to_contract[str(p.resolve())] = fn
                except Exception: pass
    except Exception: pass

    # 3. Collect files from the logs directory
    for tool_dir in ["spin", "certora", "coq", "lean", "rust_tools"]:
        d = LOGS_DIR / tool_dir
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file():
                    try:
                        entries.append({
                            "tool":     tool_dir.upper().replace("RUST_TOOLS", "RUST"),
                            "filename": f.name,
                            "path":     str(f),
                            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            "size":     _fmt_size(f.stat().st_size),
                            "category": "verification",
                            "contract": log_to_contract.get(str(f.resolve()), ""),
                        })
                    except Exception: pass

    # 4. Add "Virtual" logs from the Database (for those without files on disk)
    try:
        db_logs = AuditHistory.query.filter(AuditHistory.verification_output != '').order_by(AuditHistory.audit_date.desc()).limit(100).all()
        for row in db_logs:
            # If verification_output is content (not a path), or if path doesn't exist
            lp = row.verification_output or ""
            if lp and not (len(lp) < 500 and os.path.exists(lp)):
                entries.append({
                    "tool":     (row.tool_used or "UNKNOWN").upper(),
                    "filename": f"DB_LOG_{row.id}",
                    "path":     f"db://{row.id}",
                    "modified": row.audit_date.strftime("%Y-%m-%d %H:%M:%S") if row.audit_date else "—",
                    "size":     f"{len(lp)} chars",
                    "category": "database",
                    "contract": row.filename or "",
                })
    except Exception: pass

    entries.sort(key=lambda x: x["modified"], reverse=True)
    contracts = sorted(set(e["contract"] for e in entries if e.get("contract")))
    return render_template("logs.html", log_entries=entries, contracts=contracts)

def _fmt_size(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024: return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"

@app.route("/settings")
@login_required
def settings():
    session_keys = {
        "anthropic": bool(session.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")),
        "openai":    bool(session.get("openai_api_key")    or os.environ.get("OPENAI_API_KEY")),
    }
    return render_template("settings.html", session_keys=session_keys)

@app.route("/artifacts/<job_id>")
@login_required
def artifacts(job_id):
    import requests as _requests
    verif_url = _get_verif_url()
    job_data, artifact_files = {}, []
    try:
        resp = _requests.get(f"{verif_url}/job/{job_id}", timeout=10)
        if resp.ok: job_data = resp.json()
        art_resp = _requests.get(f"{verif_url}/artifacts/{job_id}", timeout=10)
        if art_resp.ok: artifact_files = art_resp.json().get("artifacts", [])
    except Exception: pass
    return render_template("artifacts.html", job_id=job_id, job=job_data, files=artifact_files)

# ── API Compatibility Redirects ───────────────────────────────────────────────

@app.route("/api/<path:path>", methods=["GET", "POST"])
def api_redirect(path):
    # Only redirect if it's NOT already a v1 route to avoid infinite loops or double prefixes
    if path.startswith("v1"):
        # This shouldn't happen if blueprint is working, but if it does, it's a 404
        return jsonify({"error": "Not Found"}), 404
    return redirect(f"/api/v1/{path}", code=307 if request.method == "POST" else 302)

@app.route("/admin/users")
@login_required
def admin_users():
    # Basic protection: only 'admin' role can view this
    if getattr(current_user, 'role', 'user') != 'admin':
        flash("Unauthorized access. Admin privileges required.", "danger")
        return redirect(url_for("dashboard"))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/streamlit")
@login_required
def admin_streamlit():
    if getattr(current_user, 'role', 'user') != 'admin':
        flash("Unauthorized access. Admin privileges required.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("streamlit.html")

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    if getattr(current_user, 'role', 'admin') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    if current_user.id == user_id:
        return jsonify({"error": "Cannot delete yourself"}), 400
        
    user = User.query.get_or_404(user_id)
    # Delete associated audits first
    AuditHistory.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route("/admin/users/update_role/<int:user_id>", methods=["POST"])
@login_required
def admin_update_role(user_id):
    if getattr(current_user, 'role', 'admin') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.get_json()
    new_role = data.get("role")
    if new_role not in ["admin", "user"]:
        return jsonify({"error": "Invalid role"}), 400
        
    user = User.query.get_or_404(user_id)
    user.role = new_role
    db.session.commit()
    return jsonify({"status": "success", "new_role": new_role})

# ═══════════════════════════════════════════════════════════════════════════════
# SocketIO events
# ═══════════════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def on_connect():
    state = load_state()
    if state: emit("verification_update", state)

@socketio.on("request_state")
def on_request_state():
    emit("verification_update", load_state())

# ═══════════════════════════════════════════════════════════════════════════════
# Error handlers
# ═══════════════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500

# ── Background Worker Workaround (for Render Free Tier) ───────────────────────
def _run_celery_worker():
    """Run a Celery worker in a background thread to avoid paid Render instances."""
    try:
        # Use the absolute path to the web_portal package
        import subprocess
        print("Starting background Celery worker...")
        # -P solo is used because we are in a single-process environment
        subprocess.Popen([
            "celery", "-A", "app.celery_app", "worker", 
            "--loglevel=info", "--pool=solo", "--concurrency=1"
        ], cwd=str(PORTAL_DIR))
    except Exception as e:
        print(f"Failed to start background worker: {e}")

if os.environ.get("FLASK_ENV") == "prod":
    # Prevent the worker from spawning itself recursively
    if not any(arg for arg in sys.argv if 'celery' in arg):
        eventlet.spawn(_run_celery_worker)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    socketio.run(app, host="0.0.0.0", port=port)
