"""
DeFi Guardian — Web Portal v2
Unified Flask application: portal + Streamlit dashboard features combined.
Real-time data via SocketIO file-watcher + desktop event bridge.
"""
from __future__ import annotations
import os, sys, json, re, time, threading, shutil
from datetime import datetime
from pathlib import Path

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, jsonify, send_from_directory)
from flask_login import (LoginManager, UserMixin, login_user,
                         login_required, logout_user, current_user)
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

# ── Path setup ────────────────────────────────────────────────────────────────
PORTAL_DIR  = Path(__file__).parent
PROJECT_DIR = PORTAL_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

AUDIT_LOG_FILE     = PROJECT_DIR / "generated" / "reports" / "audit_log.json"
VERIFICATION_STATE = PROJECT_DIR / "verification_state.json"
MODELS_DIR         = PROJECT_DIR / "generated" / "models"
LOGS_DIR           = PROJECT_DIR / "logs"
REPORTS_DIR        = PROJECT_DIR / "generated" / "reports"

# ── App factory ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config.update(
    SECRET_KEY    = os.environ.get("DG_SECRET_KEY", "defi-guardian-dev-secret-2026"),
    DATABASE      = str(PORTAL_DIR / "defi_guardian.db"),
    UPLOAD_FOLDER = str(PORTAL_DIR / "uploads"),
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024,   # 4 MB upload cap
)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                    logger=False, engineio_logger=False)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

# ── DB bootstrap ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(PORTAL_DIR))   # so audit_db, llm_spec, etc. resolve
from audit_db import init_db, sync_audit_log, get_user_audits, get_public_audits, seed_demo_data
init_db(app.config["DATABASE"])
seed_demo_data(app.config["DATABASE"])
sync_audit_log(app.config["DATABASE"])

# ── User model ────────────────────────────────────────────────────────────────
import sqlite3

class User(UserMixin):
    def __init__(self, id, username, email, role):
        self.id = id; self.username = username
        self.email = email; self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id,username,email,role FROM users WHERE id=?", (user_id,)
    ).fetchone()
    conn.close()
    return User(*row) if row else None

# ── Helpers ───────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn

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

def _load_state_graph() -> dict | None:
    for p in [REPORTS_DIR / "state_graph.json", VERIFICATION_STATE]:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return None

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
                    sync_audit_log(app.config["DATABASE"])
                    socketio.emit("verification_update", state)
        except Exception:
            pass
        time.sleep(2)

threading.Thread(target=_watch, daemon=True).start()

# ── Context processor ─────────────────────────────────────────────────────────
@app.context_processor
def _globals():
    return {
        "current_year": datetime.now().year,
        "app_name":     "DeFi Guardian",
        "app_version":  "2.0.0",
        "theme":        session.get("theme", "dark"),
    }

# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html", recent_audits=get_public_audits(app.config["DATABASE"], 5))

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/services")
def services():
    plans = [
        {"name": "Community", "price": "Free", "featured": False,
         "features": ["SPIN Model Checking", "3 contracts/month", "8 LTL properties", "Community support"]},
        {"name": "Professional", "price": "$49/mo", "featured": True,
         "features": ["Full 8-tool suite", "Rust verification", "Coq & Lean proofs", "Priority support", "API access"]},
        {"name": "Enterprise", "price": "Custom", "featured": False,
         "features": ["Dedicated instance", "Custom integrations", "SLA guarantee", "On-premise", "Training"]},
    ]
    return render_template("services.html", plans=plans)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        conn = _db()
        conn.execute(
            "INSERT INTO contact_messages (name,email,subject,message) VALUES (?,?,?,?)",
            (request.form.get("name",""), request.form.get("email",""),
             request.form.get("subject",""), request.form.get("message",""))
        )
        conn.commit(); conn.close()
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
        conn = _db()
        if conn.execute("SELECT 1 FROM users WHERE username=? OR email=?",
                        (username, email)).fetchone():
            conn.close()
            flash("Username or email already taken.", "danger")
            return render_template("register.html")
        conn.execute(
            "INSERT INTO users (username,email,password_hash) VALUES (?,?,?)",
            (username, email, generate_password_hash(password))
        )
        conn.commit(); conn.close()
        flash("Account created — please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","")
        password = request.form.get("password","")
        conn = _db()
        row = conn.execute(
            "SELECT id,username,email,password_hash,role FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], password):
            user = User(row["id"], row["username"], row["email"], row["role"])
            login_user(user, remember=bool(request.form.get("remember")))
            conn2 = _db()
            conn2.execute("UPDATE users SET last_login=? WHERE id=?",
                          (datetime.now(), row["id"]))
            conn2.commit(); conn2.close()
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
    sync_audit_log(app.config["DATABASE"])
    audits = get_user_audits(current_user.id, app.config["DATABASE"])
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
    return render_template("counterexample.html", audit_id="latest", audit={})

@app.route("/trace/latest")
@login_required
def trace_latest():
    return render_template("trace.html", audit_id="latest", audit={})

@app.route("/counterexample/<audit_id>")
@login_required
def counterexample_analysis(audit_id):
    # Support both int DB ids and string audit_log ids
    audit = {}
    try:
        conn = _db()
        row = conn.execute(
            "SELECT * FROM audit_history WHERE id=? AND (user_id=? OR user_id IS NULL)",
            (int(audit_id), current_user.id)
        ).fetchone()
        conn.close()
        if row:
            audit = dict(row)
    except (ValueError, TypeError):
        pass
    return render_template("counterexample.html", audit_id=audit_id, audit=audit)

@app.route("/trace/<audit_id>")
@login_required
def trace_viewer(audit_id):
    audit = {}
    try:
        conn = _db()
        row = conn.execute(
            "SELECT * FROM audit_history WHERE id=? AND (user_id=? OR user_id IS NULL)",
            (int(audit_id), current_user.id)
        ).fetchone()
        conn.close()
        if row:
            audit = dict(row)
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
    # Normalise keys so the template gets clean dicts
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

    # Build a map: absolute log_path -> contract filename from audit_log.json
    log_to_contract = {}
    try:
        audit_data = json.loads(AUDIT_LOG_FILE.read_text(encoding="utf-8"))
        for job in audit_data:
            lp = job.get("log_path", "")
            fn = job.get("file", "")
            if lp and fn:
                log_to_contract[str(Path(lp).resolve())] = fn
    except Exception:
        pass

    # Also build from DB audit_history
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT verification_output, filename FROM audit_history WHERE verification_output != ''"
        ).fetchall()
        conn.close()
        for row in rows:
            lp = row["verification_output"] or ""
            fn = row["filename"] or ""
            if lp and fn and Path(lp).exists():
                log_to_contract[str(Path(lp).resolve())] = fn
    except Exception:
        pass

    def _contract_for(path_str):
        return log_to_contract.get(str(Path(path_str).resolve()), "")

    # 1. Tool verification logs from logs/
    for tool_dir in ["spin", "certora", "coq", "lean", "rust_tools"]:
        d = LOGS_DIR / tool_dir
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file():
                    try:
                        contract = _contract_for(str(f))
                        entries.append({
                            "tool":     tool_dir.upper().replace("RUST_TOOLS", "RUST"),
                            "filename": f.name,
                            "path":     str(f),
                            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            "size":     _fmt_size(f.stat().st_size),
                            "category": "verification",
                            "contract": contract,
                        })
                    except Exception:
                        pass

    # 2. Console exports from desktop app
    console_dir = PROJECT_DIR / "console_exports"
    if console_dir.is_dir():
        for f in console_dir.iterdir():
            if f.is_file():
                try:
                    entries.append({
                        "tool":     "CONSOLE",
                        "filename": f.name,
                        "path":     str(f),
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "size":     _fmt_size(f.stat().st_size),
                        "category": "export",
                        "contract": "",
                    })
                except Exception:
                    pass

    # 3. Generated reports
    if REPORTS_DIR.is_dir():
        for f in REPORTS_DIR.iterdir():
            if f.is_file() and f.suffix in (".json", ".txt", ".log"):
                try:
                    entries.append({
                        "tool":     "REPORT",
                        "filename": f.name,
                        "path":     str(f),
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "size":     _fmt_size(f.stat().st_size),
                        "category": "report",
                        "contract": "",
                    })
                except Exception:
                    pass

    # Sort newest first
    entries.sort(key=lambda x: x["modified"], reverse=True)

    # Collect unique contracts for the filter dropdown (sorted, non-empty)
    contracts = sorted(set(e["contract"] for e in entries if e.get("contract")))

    return render_template("logs.html", log_entries=entries, contracts=contracts)


def _fmt_size(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
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

# ═══════════════════════════════════════════════════════════════════════════════
# API — State & Sync
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/state/current")
def api_state_current():
    return jsonify(load_state())

@app.route("/api/desktop-runs")
@login_required
def api_desktop_runs():
    runs = load_audit_log(50)
    return jsonify([{
        "id":        r.get("id",""),
        "timestamp": r.get("timestamp",""),
        "tool":      r.get("tool",""),
        "file":      r.get("file",""),
        "status":    r.get("status",""),
        "states":    r.get("details",{}).get("states",0),
        "depth":     r.get("details",{}).get("depth",0),
        "error_msg": r.get("details",{}).get("error_msg",""),
    } for r in runs])

@app.route("/api/sync-audit", methods=["POST"])
@login_required
def api_sync_audit():
    n = sync_audit_log(app.config["DATABASE"])
    return jsonify({"status": "success", "new_records": n})

@app.route("/api/set-theme", methods=["POST"])
def api_set_theme():
    theme = (request.get_json() or {}).get("theme", "dark")
    session["theme"] = theme
    return jsonify({"status": "success", "theme": theme})

# ═══════════════════════════════════════════════════════════════════════════════
# API — Counterexample & Trace
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/counterexample/runs")
def api_counterexample_runs():
    """Return list of all audit runs for the run selector."""
    conn = _db()
    user_id = current_user.id if current_user.is_authenticated else None
    if user_id:
        rows = conn.execute(
            """SELECT id, tool_used, filename, status, audit_date, simulated
               FROM audit_history
               WHERE user_id=? OR user_id IS NULL
               ORDER BY audit_date DESC LIMIT 200""",
            (user_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, tool_used, filename, status, audit_date, simulated
               FROM audit_history
               WHERE user_id IS NULL
               ORDER BY audit_date DESC LIMIT 50"""
        ).fetchall()
    conn.close()
    return jsonify([{
        "id":       r["id"],
        "tool":     r["tool_used"] or "?",
        "filename": r["filename"]  or "unknown",
        "status":   r["status"]    or "?",
        "date":     str(r["audit_date"] or "")[:16],
        "simulated": bool(r["simulated"] if "simulated" in r.keys() else False),
    } for r in rows])


@app.route("/api/counterexample/latest")
def api_counterexample_latest():
    """Return counterexample data for the most recent verification run."""
    # Try authenticated user's most recent record first
    user_id = current_user.id if current_user.is_authenticated else None

    conn = _db()
    if user_id:
        row = conn.execute(
            "SELECT * FROM audit_history WHERE user_id=? OR user_id IS NULL "
            "ORDER BY audit_date DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM audit_history WHERE user_id IS NULL "
            "ORDER BY audit_date DESC LIMIT 1"
        ).fetchone()
    conn.close()

    if row:
        d = dict(row)
        # Delegate to the per-audit endpoint logic by fabricating an audit_id call
        audit_id = str(d["id"])
        tool        = d.get("tool_used") or "SPIN"
        filename    = d.get("filename") or "unknown"
        status      = d.get("status") or "FAIL"
        simulated   = bool(d.get("simulated", 0))
        log_path    = d.get("verification_output") or ""
        report_path = d.get("report_path") or ""

        # Load cached trace
        trace_data = None
        for col in ("parsed_trace_json", "trace_data"):
            raw = d.get(col)
            if raw:
                try:
                    trace_data = json.loads(raw)
                    break
                except Exception:
                    pass

        # Build LTL rules from cached ltl_properties
        def _classify(formula: str) -> str:
            if not formula:
                return ""
            if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b|until", formula, re.IGNORECASE):
                return "LIVENESS"
            if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE):
                return "SAFETY"
            return ""

        rules = []
        ltl_raw = d.get("ltl_properties") or ""
        if ltl_raw:
            try:
                ltl_list = json.loads(ltl_raw)
                for r in (ltl_list if isinstance(ltl_list, list) else []):
                    if isinstance(r, dict):
                        rules.append({
                            "name":     r.get("name", ""),
                            "status":   "VERIFIED" if r.get("success") else "VIOLATED",
                            "formula":  r.get("formula", ""),
                            "category": _classify(r.get("formula", "") or r.get("name", "")),
                            "errors":   r.get("errors", 0),
                        })
            except Exception:
                pass

        # If no cached trace, try to parse or simulate
        if not trace_data:
            if tool.upper() == "SPIN" and log_path and os.path.exists(log_path):
                try:
                    output_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
                    steps, warnings = _parse_spin_output_to_steps(output_text)
                    trace_data = {"steps": steps, "final_variables": steps[-1].get("variables", {}) if steps else {}, "error_message": "", "warnings": warnings}
                except Exception:
                    pass
            elif simulated:
                trace_data = _build_simulated_trace(tool, d, rules)
            
            if not trace_data:
                trace_data = {"steps": [], "final_variables": {}, "error_message": "", "warnings": []}

            # If no rules yet, try to get from trace ltl_results
            if not rules and trace_data.get("ltl_results"):
                for r in trace_data["ltl_results"]:
                    if isinstance(r, dict):
                        rules.append({
                            "name":     r.get("name", ""),
                            "status":   "VERIFIED" if r.get("success") else "VIOLATED",
                            "formula":  r.get("formula", ""),
                            "category": _classify(r.get("formula", "") or r.get("name", "")),
                            "errors":   r.get("errors", 0),
                        })

        # If still no rules, use defaults from LTL props file
        if not rules:
            state = load_state()
            ltl = state.get("ltl_results") or state.get("spin", {}).get("ltl_results", [])
            rules = [{
                "name":     r.get("name", ""),
                "status":   "VERIFIED" if r.get("success") else "VIOLATED",
                "formula":  r.get("formula", ""),
                "category": _classify(r.get("formula", "") or r.get("name", "")),
                "errors":   r.get("errors", 0),
            } for r in ltl]

        steps = trace_data.get("steps", []) if trace_data else []
        unreached = (trace_data.get("warnings", []) if trace_data else [])

        return jsonify({
            "audit_id":         audit_id,
            "tool":             tool,
            "tool_type":        tool.upper(),
            "filename":         filename,
            "status":           status,
            "simulated":        simulated,
            "ltl_properties":   rules,
            "trace_data":       trace_data,
            "recommendations":  _spin_recs(status == "PASS", steps, ""),
            "state_graph":      _load_state_graph(),
            "output":           "",
            "unreached_states": unreached,
            "is_non_spin":      tool.upper() != "SPIN",
            "stats": {
                "states":      d.get("states_explored", 0),
                "transitions": d.get("transitions", 0),
                "depth":       d.get("depth_reached", 0),
            },
        })

    # Fallback: read verification_state.json
    state = load_state()
    if not state:
        # Return default demo data so the page renders
        demo_trace = _build_simulated_trace("SPIN", {"status": "PASS"}, [])
        return jsonify({
            "audit_id":         "latest",
            "tool":             "SPIN",
            "tool_type":        "SPIN",
            "filename":         "demo.sol",
            "status":           "PASS",
            "simulated":        True,
            "ltl_properties":   demo_trace.get("ltl_results", []),
            "trace_data":       demo_trace,
            "recommendations":  _spin_recs(True, demo_trace.get("steps", []), ""),
            "state_graph":      None,
            "output":           "",
            "unreached_states": [],
            "is_non_spin":      False,
            "stats":            {"states": 7, "transitions": 8, "depth": 15},
        })

    ltl = state.get("ltl_results") or state.get("spin", {}).get("ltl_results", [])
    def _classify2(formula):
        if not formula: return ""
        if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b", formula, re.IGNORECASE): return "LIVENESS"
        if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE): return "SAFETY"
        return ""

    rules = [{"name": r.get("name",""), "status": "VERIFIED" if r.get("success") else "VIOLATED",
               "formula": r.get("formula",""), "category": _classify2(r.get("formula","")),
               "errors": r.get("errors",0)} for r in ltl]

    spin_output = state.get("output","") or state.get("spin",{}).get("output","")
    trace_steps, unreached_states = _parse_spin_output_to_steps(spin_output, ltl)

    return jsonify({
        "audit_id":         "latest",
        "tool":             "SPIN",
        "tool_type":        "SPIN",
        "filename":         state.get("model_name","unknown"),
        "status":           "PASS" if state.get("success") else "FAIL",
        "simulated":        True,
        "ltl_properties":   rules,
        "trace_data":       {"steps": trace_steps, "final_variables": {}, "error_message": ""},
        "recommendations":  _spin_recs(state.get("success", True), trace_steps, spin_output),
        "state_graph":      _load_state_graph(),
        "output":           spin_output[:3000],
        "unreached_states": unreached_states,
        "is_non_spin":      False,
        "stats": {"states": state.get("states_stored",0), "transitions": state.get("transitions",0), "depth": state.get("depth",0)},
    })
    """Counterexample data from the most recent verification_state.json."""
    state = load_state()

    # Try to get the most recent audit record for richer data
    conn = _db()
    latest_row = conn.execute(
        "SELECT id, tool_used, filename, status, verification_output, report_path "
        "FROM audit_history WHERE user_id=? OR user_id IS NULL "
        "ORDER BY audit_date DESC LIMIT 1",
        (current_user.id,)
    ).fetchone()
    conn.close()

    # If we have a recent audit record, try parsing it with the appropriate parser.
    if latest_row and latest_row["tool_used"]:
        try:
            from trace_parsers import get_parser
            tool   = latest_row["tool_used"]
            parser = get_parser(tool)
            if parser:
                rules = parser.parse_rules(latest_row["verification_output"] or "")
                trace = parser.parse_trace(latest_row["verification_output"] or "", latest_row["report_path"] or "")
                recs  = parser.get_recommendations(latest_row["status"] or "FAIL")
                return jsonify({
                    "audit_id":        "latest",
                    "tool":            tool,
                    "tool_type":       tool.upper(),
                    "filename":        latest_row["filename"] or "unknown",
                    "status":          latest_row["status"] or "FAIL",
                    "ltl_properties":  rules,
                    "trace_data":      trace.to_dict() if trace else {"steps": [], "final_variables": {}, "error_message": ""},
                    "recommendations": recs,
                    "state_graph":     _load_state_graph(),
                    "output":          (latest_row["verification_output"] or "")[:3000],
                    "is_non_spin":     tool.upper() != "SPIN",
                    "stats":           {"states": 0, "transitions": 0, "depth": 0},
                })
        except Exception:
            app.logger.exception("Failed to parse latest audit trace")
            pass

    # Default: SPIN from verification_state.json
    if not state:
        return jsonify({"error": "No verification state found"}), 404

    ltl = state.get("ltl_results") or state.get("spin", {}).get("ltl_results", [])
    def _classify_property(formula: str) -> str:
        if not formula:
            return ""
        if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b|until", formula, re.IGNORECASE):
            return "LIVENESS"
        if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE):
            return "SAFETY"
        return ""

    rules = [{
        "name":    r.get("name",""),
        "status":  "VERIFIED" if r.get("success") else "VIOLATED",
        "formula": r.get("formula",""),
        "category": _classify_property(r.get("formula","" ) or r.get("name","")),
        "errors":  r.get("errors", 0),
    } for r in ltl]

    spin_output = state.get("output","") or state.get("spin",{}).get("output","")
    trace_steps, unreached_states = _parse_spin_output_to_steps(spin_output, ltl)

    return jsonify({
        "audit_id":        "latest",
        "tool":            "SPIN",
        "tool_type":       "SPIN",
        "filename":        state.get("model_name","unknown"),
        "status":          "PASS" if state.get("success") else "FAIL",
        "ltl_properties":  rules,
        "trace_data":      {"steps": trace_steps, "final_variables": {}, "error_message": ""},
        "recommendations": _spin_recs(state.get("success", True), trace_steps, spin_output),
        "state_graph":     _load_state_graph(),
        "output":          spin_output[:3000],
        "unreached_states": unreached_states,
        "is_non_spin":     False,
        "stats": {
            "states":      state.get("states_stored", 0),
            "transitions": state.get("transitions", 0),
            "depth":       state.get("depth", 0),
        },
    })

@app.route("/api/counterexample/<audit_id>")
@login_required
def api_counterexample(audit_id):
    # Try DB first
    try:
        conn = _db()
        row = conn.execute(
            """SELECT *
               FROM audit_history WHERE id=? AND (user_id=? OR user_id IS NULL)""",
            (int(audit_id), current_user.id)
        ).fetchone()
        conn.close()
    except (ValueError, TypeError):
        row = None

    if not row:
        return jsonify({"error": "Audit not found"}), 404

    d = dict(row)
    log_path    = d.get("verification_output") or ""
    report_path = d.get("report_path") or ""
    tool        = d.get("tool_used") or "SPIN"
    filename    = d.get("filename") or ""
    status      = d.get("status") or "FAIL"
    simulated   = bool(d.get("simulated", 0))

    # ── Load cached trace data (try both columns) ──
    trace_data = None
    for col in ("parsed_trace_json", "trace_data"):
        raw = d.get(col)
        if raw:
            try:
                trace_data = json.loads(raw)
                break
            except Exception:
                pass

    # ── Build LTL rules ──
    def _classify(formula: str) -> str:
        if not formula:
            return ""
        if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b|until", formula, re.IGNORECASE):
            return "LIVENESS"
        if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE):
            return "SAFETY"
        return ""

    rules = []
    ltl_raw = d.get("ltl_properties") or ""
    if ltl_raw:
        try:
            ltl_list = json.loads(ltl_raw)
            if isinstance(ltl_list, list):
                for r in ltl_list:
                    if isinstance(r, dict):
                        rules.append({
                            "name":    r.get("name", ""),
                            "status":  "VERIFIED" if r.get("success") else "VIOLATED",
                            "formula": r.get("formula", ""),
                            "category": _classify(r.get("formula", "") or r.get("name", "")),
                            "errors":  r.get("errors", 0),
                        })
        except Exception:
            pass

    # ── If no cached trace, parse from output ──
    if not trace_data:
        if tool.upper() == "SPIN" and log_path:
            output_text = ""
            if log_path and os.path.exists(log_path):
                try:
                    output_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
            if not output_text:
                output_text = log_path  # treat as raw output if it's not a path
            
            steps, warnings = _parse_spin_output_to_steps(output_text)
            trace_data = {
                "steps": steps,
                "final_variables": steps[-1].get("variables", {}) if steps else {},
                "error_message": "",
                "warnings": warnings,
            }
        elif simulated:
            # Build a reasonable simulated trace from LTL results
            trace_data = _build_simulated_trace(tool, d, rules)
        else:
            # Try parser
            try:
                from trace_parsers import get_parser
                parser = get_parser(tool)
                if parser:
                    trace = parser.parse_trace(log_path, report_path)
                    trace_data = trace.to_dict() if trace else None
            except Exception:
                pass

        if not trace_data:
            trace_data = {"steps": [], "final_variables": {}, "error_message": ""}

        # Persist for future requests
        if d.get("id"):
            try:
                conn2 = _db()
                conn2.execute(
                    "UPDATE audit_history SET trace_data=?, parsed_trace_json=? WHERE id=?",
                    (json.dumps(trace_data), json.dumps(trace_data), d["id"])
                )
                conn2.commit()
                conn2.close()
            except Exception:
                pass

    # ── If still no rules, parse from trace or output ──
    if not rules and trace_data:
        ltl_list = trace_data.get("ltl_results", [])
        for r in ltl_list:
            if isinstance(r, dict):
                rules.append({
                    "name":    r.get("name", "unknown"),
                    "status":  "VERIFIED" if r.get("success") else "VIOLATED",
                    "formula": r.get("formula", ""),
                    "category": _classify(r.get("formula", "") or r.get("name", "")),
                    "errors":  r.get("errors", 0),
                })

    unreached = trace_data.get("warnings", []) if trace_data else []

    return jsonify({
        "audit_id":         audit_id,
        "job_id":           d.get("job_id", ""),
        "tool":             tool,
        "tool_type":        tool.upper(),
        "filename":         filename,
        "status":           status,
        "simulated":        simulated,
        "ltl_properties":   rules,
        "trace_data":       trace_data,
        "recommendations":  _spin_recs(
            status == "PASS",
            trace_data.get("steps", []) if trace_data else [],
            log_path if os.path.exists(log_path) else "",
        ),
        "unreached_states": unreached,
        "state_graph":      _load_state_graph(),
        "output":           log_path[:3000] if not os.path.exists(log_path) else "",
        "is_non_spin":      tool.upper() != "SPIN",
        "stats": {
            "states":      d.get("states_explored", 0),
            "transitions": d.get("transitions", 0),
            "depth":       d.get("depth_reached", 0),
        },
    })

@app.route("/api/trace/<audit_id>")
@login_required
def api_trace(audit_id):
    # Handle 'latest' — use the most recent audit record
    if audit_id == "latest":
        conn = _db()
        row = conn.execute(
            "SELECT report_path,verification_output,tool_used FROM audit_history "
            "WHERE user_id=? OR user_id IS NULL ORDER BY audit_date DESC LIMIT 1",
            (current_user.id,)
        ).fetchone()
        conn.close()
    else:
        try:
            conn = _db()
            row = conn.execute(
                "SELECT report_path,verification_output,tool_used FROM audit_history WHERE id=? AND (user_id=? OR user_id IS NULL)",
                (int(audit_id), current_user.id)
            ).fetchone()
            conn.close()
        except (ValueError, TypeError):
            row = None

    if not row:
        # Fall back to building trace from verification_state.json
        state = load_state()
        if state:
            steps = _parse_spin_output_to_steps(state.get("output", ""))
            return jsonify({
                "trace": steps,
                "final_variables": {},
                "error_message": None,
                "tool": "SPIN",
            })
        return jsonify({"error": "No trace data found"}), 404

    try:
        from trace_parsers import get_parser
        parser = get_parser(row["tool_used"])
        if parser:
            trace = parser.parse_trace(row["verification_output"] or "", row["report_path"] or "")
            return jsonify({
                "trace":           [s.to_dict() for s in (trace.steps if trace else [])],
                "final_variables": trace.final_variables if trace else {},
                "error_message":   trace.error_message if trace else None,
                "tool":            row["tool_used"],
            })
    except Exception:
        pass

    return jsonify({"trace": [], "final_variables": {}, "error_message": None, "tool": row["tool_used"]})

@app.route("/api/state-graph/<audit_id>")
def api_state_graph(audit_id):
    sg = _load_state_graph()
    if sg:
        return jsonify(sg)
    # Return default DeFi lending FSM
    return jsonify({
        "nodes": [
            {"id": "INIT",       "label": "INIT",          "type": "initial",  "depth": 0, "description": "Contract deployed"},
            {"id": "IDLE",       "label": "Idle",          "type": "normal",   "depth": 0, "description": "No active position"},
            {"id": "COLLAT",     "label": "Collateralized","type": "normal",   "depth": 1, "description": "Collateral deposited"},
            {"id": "DEBT",       "label": "DebtActive",    "type": "accept",   "depth": 2, "description": "Active loan, debt ≤ col×price"},
            {"id": "REPAID",     "label": "Repaid",        "type": "normal",   "depth": 2, "description": "Loan fully repaid"},
            {"id": "LIQUIDATED", "label": "Liquidated",    "type": "error",    "depth": 3, "description": "Health factor < 150%"},
        ],
        "links": [
            {"source": "INIT",    "target": "IDLE",       "label": "deploy"},
            {"source": "IDLE",    "target": "COLLAT",     "label": "deposit(amt)"},
            {"source": "COLLAT",  "target": "IDLE",       "label": "withdraw [debt=0]"},
            {"source": "COLLAT",  "target": "DEBT",       "label": "borrow(amt)"},
            {"source": "DEBT",    "target": "REPAID",     "label": "repay(debt)"},
            {"source": "DEBT",    "target": "LIQUIDATED", "label": "liquidate [hf<150]"},
            {"source": "REPAID",  "target": "IDLE",       "label": "withdraw"},
            {"source": "LIQUIDATED", "target": "IDLE",    "label": "reset"},
        ],
        "ltl_properties": [],
        "source": "default",
    })

# ═══════════════════════════════════════════════════════════════════════════════
# API — LTL & Tool Status
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ltl-properties")
def api_ltl_properties():
    state = load_state()
    ltl = state.get("ltl_results") or state.get("spin", {}).get("ltl_results", [])
    return jsonify(ltl)

@app.route("/api/tools/status")
def api_tools_status():
    state = load_state()
    CMDS = {
        "SPIN": "spin", "COQ": "coqc", "LEAN": "lean",
        "CERTORA": "certoraRun", "KANI": "cargo-kani",
        "PRUSTI": "cargo-prusti", "CREUSOT": "cargo-creusot", "VERUS": "verus",
    }
    result = {}
    for tool, cmd in CMDS.items():
        available = shutil.which(cmd) is not None
        tool_data = state.get(tool.lower(), {})
        result[tool] = {
            "available":   available,
            "last_status": tool_data.get("status", "UNKNOWN"),
            "last_run":    tool_data.get("timestamp", ""),
            "simulated":   not available,
        }
    return jsonify(result)

def _get_verif_url():
    """Determine the verification server URL. Priority: VSERVER_URL > VERIFICATION_SERVER_URL > localhost:9000."""
    for key in ("VSERVER_URL", "VERIFICATION_SERVER_URL", "REMOTE_VERIFICATION_URL"):
        v = os.environ.get(key, "").strip()
        if v:
            return v.rstrip("/")
    return "http://localhost:9000"

# ═══════════════════════════════════════════════════════════════════════════════
# API — Run verification (simulate or real)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    """Trigger a verification run via the desktop verification server."""
    tool     = request.form.get("tool", "SPIN").upper()
    filename = request.form.get("filename", "contract")
    spec_text = request.form.get("spec_text", "")

    server_data = {"tool": tool.lower()}
    files = {}

    # ── Contract source ──
    if "file" in request.files:
        uploaded_file = request.files["file"]
        if uploaded_file and uploaded_file.filename:
            files["contract"] = (
                uploaded_file.filename,
                uploaded_file.stream,
                uploaded_file.content_type,
            )
            filename = uploaded_file.filename
    if "code" in request.form and request.form["code"].strip():
        server_data["contract_text"] = request.form["code"]
        server_data["filename"]      = filename

    # ── Spec source ──
    if "spec_file" in request.files:
        sf = request.files["spec_file"]
        if sf and sf.filename:
            files["spec"] = (sf.filename, sf.stream, sf.content_type)
    if spec_text:
        server_data["spec_text"] = spec_text

    # ── Call verification server, fall back to built-in simulator ──
    import requests as _requests

    result = None
    last_err = ""
    verif_url = _get_verif_url()

    try:
        # Read file content for fallback before stream is consumed
        file_content = None
        if files and "contract" in files:
            try:
                fname_f, stream_f, ctype_f = files["contract"]
                file_content = stream_f.read()
                files["contract"] = (fname_f, file_content, ctype_f)
            except Exception:
                pass

        resp = _requests.post(
            f"{verif_url}/verify",
            data=server_data,
            files=files if files else None,
            timeout=60,
        )
        if "text/html" in resp.headers.get("Content-Type", ""):
            raise ValueError(f"Server returned HTML (not running?)")
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:
        last_err = str(exc)
        result = None

    # ── Built-in simulator fallback ──
    if result is None:
        app.logger.warning(f"Verification server unavailable ({last_err}), using built-in simulator for {tool}")
        try:
            sys.path.insert(0, str(PORTAL_DIR))
            from verification_simulator import run_or_simulate
            
            # Save uploaded content to a temp file if we have it
            import tempfile
            tmp_path = ""
            code = server_data.get("contract_text", "")
            if not code and file_content:
                code = file_content.decode("utf-8", errors="replace") if isinstance(file_content, bytes) else file_content
            
            if code:
                ext = ".pml" if tool == "SPIN" else ".rs" if tool in ("KANI", "PRUSTI", "CREUSOT", "VERUS") else ".sol"
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8")
                tmp.write(code)
                tmp.close()
                tmp_path = tmp.name

            sim_result = run_or_simulate(
                tool=tool,
                contract_name=filename,
                source_path=tmp_path,
                specs=server_data.get("spec_text", ""),
            )
            # Clean up temp file
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            result = {
                "status": "completed",
                "job_id": f"sim-{tool.lower()}-{int(time.time())}",
                "filename": filename,
                "tool": tool,
                "simulated": sim_result.get("simulated", True),
                "stdout": sim_result.get("output", ""),
                "counterexample_found": not sim_result.get("success", True),
                "states_stored": sim_result.get("states_stored", 0),
                "transitions": sim_result.get("transitions", 0),
                "depth": sim_result.get("depth", 0),
                "trail_path": sim_result.get("trace_path", ""),
                "ltl_results": sim_result.get("ltl_results", []),
            }
        except Exception as sim_exc:
            app.logger.error(f"Simulator also failed: {sim_exc}")
            return jsonify({"error": f"Verification server unavailable and simulator failed: {sim_exc}"}), 503

    # ── Persist to audit_history ──
    job_id = result.get("job_id", "")
    status_val = result.get("status", "")
    simulated = int(result.get("simulated", False))
    
    if status_val == "accepted":
        audit_status = "PENDING"
    elif result.get("counterexample_found"):
        audit_status = "FAIL"
    else:
        audit_status = "PASS"

    # Parse trace data for immediate persistence
    trace_json = None
    ltl_results = result.get("ltl_results", [])
    if ltl_results:
        trace_json = json.dumps({
            "ltl_results": ltl_results,
            "steps": [],
            "final_variables": {},
            "error_message": "",
        })
    
    conn = _db()
    conn.execute("""
        INSERT INTO audit_history
          (user_id, job_id, filename, file_type, tool_used, status,
           states_explored, transitions, depth_reached,
           verification_output, report_path, trace_data, parsed_trace_json,
           simulated, specs_used)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        current_user.id,
        job_id,
        filename,
        os.path.splitext(filename)[1] or "",
        tool,
        audit_status,
        result.get("states_stored", 0),
        result.get("transitions", 0),
        result.get("depth", 0),
        result.get("stdout", "")[:8000],
        result.get("trail_path", "") or "",
        trace_json,
        trace_json,
        simulated,
        server_data.get("spec_text", "")[:2000],
    ))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    try:
        socketio.emit("verification_complete", {
            "tool":       tool,
            "filename":   filename,
            "status":     audit_status,
            "audit_id":   new_id,
            "job_id":     job_id,
            "simulated":  bool(simulated),
        })
    except Exception:
        pass

    return jsonify({**result, "audit_id": new_id})


@app.route("/api/job/<job_id>")
@login_required
def api_job_status(job_id):
    """Proxy job status from the verification server, or return local simulator result."""
    # If this is a simulator job (job_id starts with 'sim-'), return the DB record directly
    if job_id.startswith("sim-"):
        conn = _db()
        row = conn.execute(
            "SELECT * FROM audit_history WHERE job_id=? AND (user_id=? OR user_id IS NULL)",
            (job_id, current_user.id)
        ).fetchone()
        conn.close()
        if row:
            d = dict(row)
            trace = None
            for col in ("parsed_trace_json", "trace_data"):
                if d.get(col):
                    try:
                        trace = json.loads(d[col])
                        break
                    except Exception:
                        pass
            return jsonify({
                "status": "completed",
                "job_id": job_id,
                "result": {
                    "status": d.get("status", "PASS"),
                    "stdout": d.get("verification_output", ""),
                    "counterexample_found": d.get("status") == "FAIL",
                    "states_stored": d.get("states_explored", 0),
                    "transitions": d.get("transitions", 0),
                    "depth": d.get("depth_reached", 0),
                    "simulated": bool(d.get("simulated", 1)),
                },
                "parsed_trace": trace,
                "audit_id": d.get("id"),
            })
        return jsonify({"status": "not_found"}), 404

    import requests as _requests
    verif_url = _get_verif_url()
    try:
        resp = _requests.get(f"{verif_url}/job/{job_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # If completed, update audit_history status
        if data.get("status") == "completed" and data.get("result"):
            r = data["result"]
            parsed_trace = data.get("parsed_trace")
            
            # Extract stats from stdout if not provided in result
            stdout = r.get("stdout", "")
            states = r.get("states_stored", 0)
            transitions = r.get("transitions", 0)
            depth = r.get("depth", 0)
            
            if not states:
                import re as _re
                m = _re.search(r"(\d+) states, stored", stdout)
                if m: states = int(m.group(1))
            if not transitions:
                import re as _re
                m = _re.search(r"(\d+) transitions", stdout)
                if m: transitions = int(m.group(1))
            if not depth:
                import re as _re
                m = _re.search(r"depth reached (\d+)", stdout)
                if m: depth = int(m.group(1))

            trace_json = json.dumps(parsed_trace) if parsed_trace else None
            
            conn = _db()
            conn.execute("""
                UPDATE audit_history
                SET status=?, 
                    verification_output=?, 
                    report_path=?, 
                    trace_data=?,
                    parsed_trace_json=?,
                    states_explored=?,
                    transitions=?,
                    depth_reached=?
                WHERE job_id=?
            """, (
                "PASS" if not r.get("counterexample_found") else "FAIL",
                stdout[:8000],
                r.get("trail_path", "") or "",
                trace_json,
                trace_json,
                states,
                transitions,
                depth,
                job_id
            ))
            conn.commit()
            conn.close()
        return jsonify(data)
    except _requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Verification server not running"}), 503
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/artifacts/<job_id>")
@login_required
def artifacts(job_id):
    """Artifacts dashboard for a verification job."""
    import requests as _requests
    verif_url = _get_verif_url()
    job_data = {}
    artifact_files = []
    try:
        resp = _requests.get(f"{verif_url}/job/{job_id}", timeout=10)
        if resp.ok:
            job_data = resp.json()
        art_resp = _requests.get(f"{verif_url}/artifacts/{job_id}", timeout=10)
        if art_resp.ok:
            artifact_files = art_resp.json().get("artifacts", [])
    except Exception:
        pass
    return render_template("artifacts.html", job_id=job_id, job=job_data, files=artifact_files)


@app.route("/api/artifact/<job_id>/<filename>")
@login_required
def api_download_artifact(job_id, filename):
    """Proxy file download from the verification server."""
    import requests as _requests
    verif_url = _get_verif_url()
    try:
        resp = _requests.get(f"{verif_url}/download/{job_id}/{filename}", stream=True, timeout=30)
        resp.raise_for_status()
        
        from flask import Response
        return Response(
            resp.iter_content(chunk_size=8192),
            content_type=resp.headers.get('Content-Type'),
            headers={
                "Content-Disposition": resp.headers.get('Content-Disposition', f'attachment; filename={filename}')
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    """Accept a file upload and save it to the uploads folder."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400
    from werkzeug.utils import secure_filename
    fname = secure_filename(f.filename)
    dest  = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    f.save(dest)
    return jsonify({"status": "ok", "filename": fname, "path": dest})

# ═══════════════════════════════════════════════════════════════════════════════
# API — LLM Spec Generation
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/generate-spec", methods=["POST"])
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

@app.route("/api/save-spec", methods=["POST"])
@login_required
def api_save_spec():
    """Save LTL/CVL spec to the project directory.

    Always writes a .spec file to two locations:
      - generated/specs/{name}.spec   (canonical project location)
      - certora/specs/{name}.spec     (CVL only — where Certora looks)
      - generated/reports/{name}.spec (legacy reports folder)
    Also writes tool-native copies (.txt for LTL, .cvl for CVL).
    """
    data = request.get_json() or {}
    ltl  = data.get("ltl", "")
    cvl  = data.get("cvl", "")
    # Optional contract name for the filename (e.g. "SimpleLending")
    name = data.get("name", "").strip()
    # Sanitise: keep only alphanumeric, dash, underscore, dot
    import re as _re
    safe_name = _re.sub(r'[^A-Za-z0-9_\-\.]', '_', name) if name else ""

    # Directories
    specs_dir    = PROJECT_DIR / "generated" / "specs"
    reports_dir  = PROJECT_DIR / "generated" / "reports"
    certora_dir  = PROJECT_DIR / "certora"   / "specs"
    for d in (specs_dir, reports_dir, certora_dir):
        d.mkdir(parents=True, exist_ok=True)

    saved = []
    try:
        if ltl:
            ltl_stem = f"{safe_name}_ltl" if safe_name else "saved_ltl"

            # 1. Canonical .spec in generated/specs/
            p = specs_dir / f"{ltl_stem}.spec"
            p.write_text(ltl, encoding="utf-8")
            saved.append(str(p))

            # 2. Mirror in generated/reports/ (legacy)
            p2 = reports_dir / f"{ltl_stem}.spec"
            p2.write_text(ltl, encoding="utf-8")
            saved.append(str(p2))

            # 3. Native .txt copy (SPIN / text editors)
            (specs_dir / f"{ltl_stem}.txt").write_text(ltl, encoding="utf-8")

        if cvl:
            cvl_stem = f"{safe_name}" if safe_name else "saved_cvl"

            # 1. Canonical .spec in generated/specs/
            p = specs_dir / f"{cvl_stem}.spec"
            p.write_text(cvl, encoding="utf-8")
            saved.append(str(p))

            # 2. Certora-standard location: certora/specs/{name}.spec
            p2 = certora_dir / f"{cvl_stem}.spec"
            p2.write_text(cvl, encoding="utf-8")
            saved.append(str(p2))

            # 3. Native .cvl copy (Certora CLI)
            (certora_dir / f"{cvl_stem}.cvl").write_text(cvl, encoding="utf-8")

        return jsonify({"status": "success", "saved": saved})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════════════════════════
# API — Specs
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/specs", methods=["GET"])
@login_required
def api_list_specs():
    """List available saved specification files."""
    specs_dir = PROJECT_DIR / "generated" / "specs"
    if not specs_dir.exists():
        return jsonify([])
    specs = []
    for f in specs_dir.iterdir():
        if f.suffix in ('.spec', '.txt', '.cvl'):
            specs.append({"name": f.name, "path": str(f)})
    return jsonify(specs)

@app.route("/api/specs/<name>", methods=["GET"])
@login_required
def api_get_spec(name):
    """Load a saved specification file."""
    specs_dir = PROJECT_DIR / "generated" / "specs"
    spec_path = specs_dir / name
    if not spec_path.exists():
        return jsonify({"error": "Spec not found"}), 404
    try:
        content = spec_path.read_text(encoding="utf-8")
        return jsonify({"name": name, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/events/emit", methods=["POST"])
def api_emit_event():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    socketio.emit("verification_complete", data)
    sync_audit_log(app.config["DATABASE"])
    return jsonify({"status": "success"})

# ═══════════════════════════════════════════════════════════════════════════════
# API — Log content
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/log-content")
@login_required
def api_log_content():
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    if not os.path.abspath(path).startswith(str(PROJECT_DIR)):
        return jsonify({"error": "Access denied"}), 403
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")[:60000]
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════════════════════════
# SocketIO events
# ═══════════════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def on_connect():
    state = load_state()
    if state:
        emit("verification_update", state)

@socketio.on("request_state")
def on_request_state():
    emit("verification_update", load_state())

@socketio.on("request_tools")
def on_request_tools():
    # Reuse the tools status logic
    with app.test_request_context():
        pass  # just emit current state
    emit("tools_update", {})

# ═══════════════════════════════════════════════════════════════════════════════
# Error handlers
# ═══════════════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500

# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _build_simulated_trace(tool: str, audit_row: dict, rules: list) -> dict:
    """Build a realistic trace structure for simulated verification results."""
    tool_up = tool.upper()
    steps = []
    
    if tool_up == "SPIN":
        # Simulate DeFi lending FSM trace
        sim_vars = [
            {"state": 0, "user_collateral": 0, "user_debt": 0, "lock": 0, "amount": 0, "health_factor": 200},
            {"state": 0, "user_collateral": 1000, "user_debt": 0, "lock": 0, "amount": 1000, "health_factor": 200},
            {"state": 1, "user_collateral": 1000, "user_debt": 0, "lock": 0, "amount": 1000, "health_factor": 200},
            {"state": 1, "user_collateral": 1000, "user_debt": 500, "lock": 0, "amount": 500, "health_factor": 150},
            {"state": 2, "user_collateral": 1000, "user_debt": 500, "lock": 0, "amount": 500, "health_factor": 150},
            {"state": 2, "user_collateral": 1000, "user_debt": 0, "lock": 0, "amount": 500, "health_factor": 200},
            {"state": 3, "user_collateral": 0, "user_debt": 0, "lock": 0, "amount": 0, "health_factor": 200},
        ]
        actions = ["init", "deposit(1000)", "collateralized", "borrow(500)", "debt_active", "repay(500)", "withdraw_all"]
        proc_names = ["Contract", "Contract", "Contract", "Contract", "Contract", "Contract", "Contract"]
        
        for i, (vars_snapshot, action, proc) in enumerate(zip(sim_vars, actions, proc_names)):
            prev = sim_vars[i-1] if i > 0 else vars_snapshot
            updates = {k: str(v) for k, v in vars_snapshot.items() if v != prev.get(k, v)}
            is_err = any(r.get("status") == "VIOLATED" for r in rules) and i == len(sim_vars) - 1
            steps.append({
                "step": i,
                "proc_id": 0,
                "proc_name": proc,
                "line": 10 + i * 5,
                "state": vars_snapshot.get("state", i),
                "action": action,
                "variables": {k: str(v) for k, v in vars_snapshot.items()},
                "variables_before": {k: str(v) for k, v in prev.items()},
                "variables_after": {k: str(v) for k, v in vars_snapshot.items()},
                "updates": updates,
                "is_error": is_err,
            })
    elif tool_up in ("COQ", "LEAN"):
        # Theorem prover steps
        theorems = ["all_values_non_negative", "safety_no_overflow", "reentrancy_guard", "collateral_invariant"]
        for i, thm in enumerate(theorems):
            passed = not any(r.get("status") == "VIOLATED" for r in rules)
            steps.append({
                "step": i,
                "proc_id": 0,
                "proc_name": tool_up,
                "action": f"theorem {thm}: " + ("Qed." if passed else "Admitted."),
                "variables": {"proved": str(passed)},
                "variables_before": {},
                "variables_after": {"proved": str(passed)},
                "updates": {},
                "is_error": not passed and i == len(theorems) - 1,
            })
    else:
        # Generic tool steps
        steps.append({
            "step": 0,
            "proc_id": 0,
            "proc_name": tool_up,
            "action": "verification_complete",
            "variables": {"status": audit_row.get("status", "PASS")},
            "variables_before": {},
            "variables_after": {"status": audit_row.get("status", "PASS")},
            "updates": {},
            "is_error": audit_row.get("status") == "FAIL",
        })

    ltl_results = []
    for r in rules:
        ltl_results.append({
            "name": r.get("name", ""),
            "success": r.get("status") != "VIOLATED",
            "formula": r.get("formula", ""),
            "errors": r.get("errors", 0),
        })

    return {
        "steps": steps,
        "final_variables": steps[-1].get("variables", {}) if steps else {},
        "error_message": "",
        "warnings": [],
        "ltl_results": ltl_results,
        "simulated": True,
    }


def _property_category(formula: str) -> str:
    if not formula:
        return ""
    if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b|until", formula, re.IGNORECASE):
        return "LIVENESS"
    if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE):
        return "SAFETY"
    return ""


def _parse_spin_output_to_steps(output: str, ltl_results: list[dict] | None = None) -> tuple[list, list[str]]:
    """Extract detailed trace steps from raw SPIN output for the viewer."""
    import re
    steps = []
    warnings: list[str] = []
    if not output:
        return steps, warnings

    formula_map = {}
    if ltl_results:
        formula_map = {r.get("name", ""): r.get("formula", "") for r in ltl_results}

    # Capture unreachable claim/proctype sections from SPIN output.
    unreached_pat = re.compile(
        r"unreached in (proctype|claim) ([\w_]+)\s*\n((?:\s+.*\n)+?)(?=\n\s*pan:|\n\n|$)",
        re.IGNORECASE,
    )
    for m in unreached_pat.finditer(output):
        category = m.group(1)
        name = m.group(2)
        lines = [ln for ln in m.group(3).splitlines() if ln.strip()]
        warnings.append(
            f"Unreached {category} '{name}' with {len(lines)} unreachable trace lines."
        )

    # Parse detailed trace steps from SPIN output
    # Pattern for trace lines: "  2:	proc  0 (Contract:1) /path/file.pml:32 (state 1)	[action]"
    # More robust pattern to handle process names with colons (like :init:) and varying whitespace
    trace_pattern = re.compile(
        r"^\s*(\d+):\s*proc\s+(\d+)\s*\((.*?):\d+\)\s*(.*?):(\d+)\s*\(state\s+(\d+)\)\s*\[(.*?)\]",
        re.MULTILINE
    )

    # Pattern for variable assignments in actions: "var = value" within brackets
    var_pattern = re.compile(r"(?<![=!<>])\b([A-Za-z_]\w*)\s*=\s*([^=][^,;\]]*)")
    assignment_pattern = re.compile(r"(?<![=!<>])\b([A-Za-z_]\w*)\s*=\s*([^=][^,;\]]*)")

    current_vars = {}

    for match in trace_pattern.finditer(output):
        step_num = int(match.group(1))
        proc_id = int(match.group(2))
        proc_name = match.group(3).strip()
        file_path = match.group(4)
        line_num = int(match.group(5))
        state_id = int(match.group(6))
        action = match.group(7).strip()

        # Extract variable updates from action - avoid comparisons like == or <=
        updates = {}
        step_vars_before = current_vars.copy()
        if action and '=' in action:
            for part in re.split(r'[;,]', action):
                part = part.strip()
                assign_match = assignment_pattern.match(part)
                if assign_match:
                    var_name = assign_match.group(1).strip()
                    var_value = assign_match.group(2).strip()
                    updates[var_name] = var_value
                    current_vars[var_name] = var_value

        is_error = bool(re.search(r"\b(assert|violation|error|claim)\b", action, re.IGNORECASE))
        if not is_error and proc_name == "-":
            is_error = True
        if not is_error and re.search(r"reachability|liveness|claim", proc_name, re.IGNORECASE):
            is_error = True

        # Create step with before/after variables
        step = {
            "step": step_num,
            "proc_id": proc_id,
            "proc_name": proc_name,
            "line": line_num,
            "file": file_path,
            "state": state_id,
            "variables_before": step_vars_before,
            "variables_after": current_vars.copy(),
            "updates": updates,
            "variables": current_vars.copy(),
            "raw": match.group(0).strip(),
            "action": action,
            "is_error": is_error,
        }
        steps.append(step)

    # Parse final variable values from the end of SPIN output and update the last step
    final_vars_pattern = re.compile(r"^\s*(\w+)\s*=\s*(.+)$", re.MULTILINE)
    final_vars_section = re.search(r"spin: trail ends after \d+ steps.*?(?=^\s*\d+:|\Z)", output, re.DOTALL | re.MULTILINE)
    if final_vars_section and steps:
        final_vars = {}
        for match in final_vars_pattern.finditer(final_vars_section.group(0)):
            var_name = match.group(1).strip()
            var_value = match.group(2).strip()
            final_vars[var_name] = var_value
        steps[-1]["variables_after"] = final_vars
        steps[-1]["variables"] = final_vars

    # Mark the last step as error if the trail ended in a denial/acceptance cycle and no explicit error step was found.
    if steps and not any(s.get("is_error") for s in steps):
        if re.search(r"acceptance cycle|assertion violated|error|violation", output, re.IGNORECASE):
            steps[-1]["is_error"] = True
            steps[-1]["category"] = steps[-1].get("category") or "LIVENESS"

    # Mark error steps based on LTL violations
    sections = re.split(r"--- LTL (\w+) ---", output)
    for i in range(1, len(sections), 2):
        name = sections[i]
        body = sections[i + 1]
        errors = 0
        acceptance_cycle = False

        err_match = re.search(r"errors:\s*([0-9]+)", body)
        if err_match:
            errors = int(err_match.group(1))

        cycle_match = re.search(r"acceptance cycle \(at depth\s*([0-9]+)\)", body, re.IGNORECASE)
        if cycle_match:
            acceptance_cycle = True

        if errors > 0 or acceptance_cycle:
            # Find the step where this LTL property failed
            for step in steps:
                if step.get("proc_name") == name or name in step.get("action", ""):
                    step["is_error"] = True
                    step["category"] = _property_category(formula_map.get(name, "") or name)
                    break

    return steps, warnings

def _spin_recs(passed: bool, trace_steps: list[dict] | None = None, output: str = "") -> list[str]:
    if passed:
        return [
            "All LTL properties verified — no counterexample found.",
            "Consider adding more invariants to strengthen the specification.",
            "Run mutation testing with Gambit to validate rule coverage.",
        ]

    recommendations = []
    failure_type = "unknown"
    depth = None
    if output:
        lower_output = output.lower()
        if "acceptance cycle" in lower_output:
            failure_type = "liveness"
            m = re.search(r"acceptance cycle \(at depth\s*([0-9]+)\)", output, re.IGNORECASE)
            if m:
                depth = int(m.group(1))
        elif "assertion violated" in lower_output or "assert(" in lower_output:
            failure_type = "safety"
        elif "error" in lower_output or "violation" in lower_output:
            failure_type = "safety"

    error_step = None
    if trace_steps:
        for step in trace_steps:
            if step.get("is_error"):
                error_step = step
                break
        if not error_step and trace_steps:
            error_step = trace_steps[-1]

    step_num = error_step.get("step") if error_step else None
    vars_after = {}
    if error_step:
        vars_after = error_step.get("variables_after") or error_step.get("variables") or {}

    details = []
    for key in ("user_collateral", "user_debt", "health_factor", "liquidation_executed", "amount", "price_eth", "state"):
        if key in vars_after:
            details.append(f"{key}={vars_after[key]}")

    if failure_type == "liveness":
        recommendations.append(
            f"Step {step_num or '?'}: acceptance cycle detected; this is a liveness/fairness violation and means the model may loop without reaching progress."
        )
        if depth is not None:
            recommendations.append(
                f"The cycle was found at depth {depth}. Consider adding a fairness constraint or stronger progress guard to eliminate the loop."
            )
    elif failure_type == "safety":
        recommendations.append(
            f"Step {step_num or '?'}: safety violation detected. Inspect the violated assertion and variable values at this point."
        )
    else:
        recommendations.append(
            f"Step {step_num or '?'}: counterexample found. Review the trace and variable values to determine whether this is a safety or liveness failure."
        )

    if details:
        recommendations.append(
            f"Key values at the failing step: {', '.join(details[:5])}."
        )

    if output and "unreached in" in output.lower():
        recommendations.append(
            "Some claims or proctypes were never reached during search; this often indicates dead or unreachable model behavior."
        )

    recommendations.extend([
        "Review the LTL property and its encoder to ensure the intended behavior is captured.",
        "Inspect variable values at each step to identify the root cause.",
        "Consider adding require() guards or fairness constraints depending on the failure type.",
    ])
    return recommendations

# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, debug=False, port=port,
                 use_reloader=False, allow_unsafe_werkzeug=True)
