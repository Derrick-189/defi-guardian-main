"""
DeFi Guardian — Audit Database models and helpers
Using SQLAlchemy for cross-database compatibility (SQLite/PostgreSQL).
"""
from __future__ import annotations
import os, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import text

db = SQLAlchemy()

PROJECT_DIR = Path(__file__).parent.parent
AUDIT_LOG   = PROJECT_DIR / "generated" / "reports" / "audit_log.json"

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    organization = db.Column(db.String(120))
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login = db.Column(db.DateTime)
    audits = db.relationship('AuditHistory', backref='user', lazy=True)

class AuditHistory(db.Model):
    __tablename__ = 'audit_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    job_id = db.Column(db.String(100))
    filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(20))
    tool_used = db.Column(db.String(50))
    status = db.Column(db.String(20))
    states_explored = db.Column(db.Integer, default=0)
    transitions = db.Column(db.Integer, default=0)
    depth_reached = db.Column(db.Integer, default=0)
    vulnerabilities_found = db.Column(db.Text)
    ltl_properties = db.Column(db.Text)
    verification_output = db.Column(db.Text)
    trace_data = db.Column(db.Text)
    source_code = db.Column(db.Text)
    audit_date = db.Column(db.DateTime, default=datetime.now)
    report_path = db.Column(db.String(500))

class ContactMessage(db.Model):
    __tablename__ = 'contact_messages'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)

def init_db(app) -> None:
    db.init_app(app)
    with app.app_context():
        # Ensure the directory for the database exists (especially for persistent disks)
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if db_uri.startswith("sqlite:///"):
            db_path = Path(db_uri.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)
            
        db.create_all()

def _read_log_content(log_path: str, max_bytes: int = 50000) -> str:
    """
    Read a log file and return its content.
    Tries the direct path first, then attempts to relocate it relative to
    PROJECT_DIR in case the file was written on a different machine
    (e.g. desktop → Render ephemeral disk).
    Returns empty string if the file cannot be found.
    """
    if not log_path:
        return ""

    def _try(p: Path) -> str:
        try:
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        except Exception:
            pass
        return ""

    # 1. Direct path (works locally)
    content = _try(Path(log_path))
    if content:
        return content

    # 2. Re-anchor to PROJECT_DIR using the path segment after a known marker
    for marker in ("logs/", "generated/", "uploads/", "console_exports/"):
        if marker in log_path:
            rel = log_path.split(marker, 1)[-1]
            content = _try(PROJECT_DIR / marker.rstrip("/") / rel)
            if content:
                return content

    return ""

def _read_trail_content(trail_path: str = None) -> str:
    """
    Read a .trail file for SPIN counterexample traces.
    Used to provide trace steps even when the original log file is missing.
    """
    candidates = [
        PROJECT_DIR / "translated_output.pml.trail",
        PROJECT_DIR / "generated" / "models" / "translated_output.pml.trail",
        PROJECT_DIR / "logs" / "spin" / "translated_output.pml.trail",
        PROJECT_DIR / "outputs" / "translated_output.pml.trail",
    ]
    if trail_path:
        candidates.insert(0, Path(trail_path))
    for c in candidates:
        try:
            if c.exists() and c.is_file():
                return c.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return ""


def sync_audit_log(audit_jobs: list | None = None, users: list | None = None) -> int:
    """
    Import desktop audit_log.json into DB.
    Inlines log file content so records remain useful on Render where the
    original desktop file paths don't exist.
    Also syncs user accounts if provided.
    Returns count of new audit rows added.
    """
    if users:
        from werkzeug.security import generate_password_hash
        for u in users:
            uname = u.get("username")
            if not uname: continue
            existing_user = User.query.filter_by(username=uname).first()
            if not existing_user:
                new_user = User(
                    username=uname,
                    email=u.get("email", f"{uname}@defiguardian.local"),
                    password_hash=u.get("password_hash") or generate_password_hash("default1234"),
                    role=u.get("role", "user"),
                    organization=u.get("organization")
                )
                db.session.add(new_user)
        db.session.commit()

    if audit_jobs is None:
        if not AUDIT_LOG.exists():
            return 0
        try:
            audit_jobs = json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
        except Exception:
            return 0

    jobs = audit_jobs


    new_count = 0
    for job in jobs:
        filename = job.get("file", "")
        tool     = job.get("tool", "")
        timestamp_str = job.get("timestamp") or job.get("audit_date", "")

        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        # ── Read log content ─────────────────────────────────────────────────
        # Prefer inlined content from sync script if available
        log_content = job.get("log_content")
        log_path    = job.get("log_path", "")
        
        if not log_content:
            log_content = _read_log_content(log_path)
            
            # If log_path was relative to console_exports, try that too
            if not log_content and "console_exports" in log_path:
                rel = log_path.split("console_exports/", 1)[-1]
                log_content = _read_log_content(str(PROJECT_DIR / "console_exports" / rel))
            
        specs = job.get("specs", "")
        
        if not log_content:
            # Log file not available - create synthetic content from specs
            ltl_formulas = []
            for m in re.finditer(r"ltl\s+(\w+)\s*\{([^}]+)\}", specs or ""):
                ltl_formulas.append(f"ltl {m.group(1)} {{ {m.group(2)} }}")
            
            log_content = f"[LOG_NOT_FOUND: {log_path}]\n\n"
            log_content += "\n".join(ltl_formulas) + "\n"
            log_content += f"\n--- LTL safety_no_overflow ---\nerrors: -1\n"

        # ── Also inline trail file content for SPIN to extract trace steps ───
        trail_path = job.get("trace_path") or job.get("trail_path", "")
        trail_content = job.get("trail_content")
        if not trail_content and trail_path:
            trail_content = _read_trail_content(trail_path)
        if not trail_content:
            trail_content = _read_trail_content()
            
        if trail_content:
            log_content = f"=== TRAIL TRACE ===\n{trail_content}\n=== LOG OUTPUT ===\n{log_content}"

        # Parse LTL results and determine status
        ltl_results = _parse_ltl_results(log_content, specs)
        ltl_results_json = json.dumps(ltl_results)
        
        raw = job.get("status", "").upper()
        # A run is FAIL if SPIN found errors, OR if any LTL property was violated
        has_violations = any(r.get("status") == "VIOLATED" for r in ltl_results)
        spin_errors = 0
        if "errors: " in log_content:
            try:
                # Find the maximum error count across all LTL properties in the log
                error_counts = [int(e) for e in re.findall(r"errors:\s*(\d+)", log_content)]
                spin_errors = max(error_counts) if error_counts else 0
            except Exception: pass
            
        status = "PASS" if (raw in ("SUCCESS", "PASSED", "PASS") and not has_violations and spin_errors == 0) else "FAIL"

        existing = AuditHistory.query.filter_by(
            filename=filename,
            tool_used=tool,
            audit_date=timestamp
        ).first()

        if existing:
            # ── Update existing record if it only contains a path ────────────
            vo = existing.verification_output or ""
            if vo and "\n" not in vo and len(vo) < 600:
                existing.verification_output = log_content
                existing.status = status
                existing.ltl_properties = ltl_results_json
            db.session.add(existing)
            continue

        det = job.get("details", {})
        new_audit = AuditHistory(
            filename=filename,
            file_type=os.path.splitext(filename)[1] or "",
            tool_used=tool,
            status=status,
            states_explored=det.get("states", 0),
            transitions=det.get("transitions", 0),
            depth_reached=det.get("depth", 0),
            vulnerabilities_found=det.get("error_msg", ""),
            ltl_properties=ltl_results_json,
            verification_output=log_content,
            audit_date=timestamp,
            report_path=trail_path or log_path,
        )
        db.session.add(new_audit)
        new_count += 1

    db.session.commit()
    return new_count


def _parse_ltl_results(log_content: str, specs: str) -> list[dict]:
    """
    Parse LTL property results from log content.
    Returns list of dicts with name, status, success, errors, formula.
    If log content is unavailable, extracts property names and formulas from specs.
    """
    results = []
    if not log_content and not specs:
        return results

    formula_pattern = re.compile(r"ltl\s+(\w+)\s*\{([^}]+)\}")
    
    formulas = {}
    for m in formula_pattern.finditer(specs or ""):
        formulas[m.group(1)] = m.group(2)

    # Match LTL sections in SPIN output
    ltl_pattern = re.compile(
        r"---\s*LTL\s+(\w+)\s*---.*?errors:\s*(\d+)",
        re.DOTALL | re.IGNORECASE,
    )

    for m in ltl_pattern.finditer(log_content or ""):
        name = m.group(1)
        try:
            errors = int(m.group(2))
        except (ValueError, TypeError):
            errors = 0
            
        # If the log explicitly contains "acceptance cycle", it's a violation even if errors: 1 wasn't parsed correctly
        status = "VIOLATED" if errors > 0 else "VERIFIED"
        
        # Check for acceptance cycle or error markers in the specific section
        try:
            # Case-insensitive search for the LTL section to be more robust
            section_start = log_content.lower().find(f"--- ltl {name.lower()} ---")
            if section_start != -1:
                remaining = log_content[section_start:]
                next_section = remaining.lower().find("--- ltl", 10)
                if next_section != -1:
                    section = remaining[:next_section].lower()
                else:
                    section = remaining.lower()
                    
                if "acceptance cycle" in section or "error:" in section or "violated" in section:
                    status = "VIOLATED"
                    errors = max(errors, 1)
        except Exception: pass

        results.append({
            "name": name,
            "status": status,
            "success": status == "VERIFIED",
            "errors": errors,
            "formula": formulas.get(name, ""),
        })

    # If no LTL results found in log but we have specs, extract property definitions
    # This handles the case where log files don't exist on the server
    if not results and formulas:
        for name, formula in formulas.items():
            results.append({
                "name": name,
                "status": "UNKNOWN",
                "success": False,
                "errors": -1,
                "formula": formula,
            })

    return results

def get_user_audits(user_id: Optional[int], limit: int = 100):
    query = AuditHistory.query
    if user_id:
        query = query.filter((AuditHistory.user_id == user_id) | (AuditHistory.user_id == None))
    else:
        query = query.filter(AuditHistory.user_id == None)
    
    results = query.order_by(AuditHistory.audit_date.desc()).limit(limit).all()
    return [
        {
            'id': r.id,
            'user_id': r.user_id,
            'filename': r.filename,
            'file_type': r.file_type,
            'tool_used': r.tool_used,
            'status': r.status,
            'states_explored': r.states_explored,
            'transitions': r.transitions,
            'depth_reached': r.depth_reached,
            'vulnerabilities_found': r.vulnerabilities_found,
            'ltl_properties': r.ltl_properties,
            'verification_output': r.verification_output,
            'audit_date': r.audit_date.isoformat() if r.audit_date else None,
            'report_path': r.report_path
        } for r in results
    ]

def get_public_audits(limit: int = 10):
    results = AuditHistory.query.order_by(AuditHistory.audit_date.desc()).limit(limit).all()
    return [
        {
            'filename': r.filename,
            'file_type': r.file_type,
            'tool_used': r.tool_used,
            'status': r.status,
            'states_explored': r.states_explored,
            'depth_reached': r.depth_reached,
            'audit_date': r.audit_date.isoformat() if r.audit_date else None
        } for r in results
    ]

def migrate_path_only_records() -> int:
    """
    Migration: Update existing AuditHistory records that only have file paths
    in verification_output to inline the actual content (if the file exists)
    or mark them as missing and derive LTL results from specs.
    
    Returns count of updated records.
    """
    updated = 0
    for record in AuditHistory.query.all():
        vo = record.verification_output or ""
        # Check if this looks like a path-only record (no newlines, short)
        if vo and "\n" not in vo and len(vo) < 600:
            content = _read_log_content(vo)
            if content:
                record.verification_output = content
                updated += 1
            else:
                # Log file not available - mark it and derive from specs
                specs = record.ltl_properties or ""
                ltl_formulas = []
                for m in re.finditer(r"ltl\s+(\w+)\s*\{([^}]+)\}", specs or ""):
                    ltl_formulas.append(f"ltl {m.group(1)} {{ {m.group(2)} }}")
                
                record.verification_output = f"[LOG_NOT_FOUND: {vo}]\n\n"
                record.verification_output += "\n".join(ltl_formulas) + "\n"
                record.verification_output += f"\n--- LTL safety_no_overflow ---\nerrors: -1\n"
                
                # Derive LTL results from specs since log is unavailable
                if specs:
                    ltl_results = json.dumps(_parse_ltl_results("", specs))
                    if ltl_results and ltl_results != "[]":
                        record.ltl_properties = ltl_results
                updated += 1
    db.session.commit()
    return updated


def seed_demo_data() -> None:
    """Insert demo user + realistic audit records if DB is empty."""
    from werkzeug.security import generate_password_hash

    _SPIN_DEMO_OUTPUT = """\
ltl safety_no_overflow { [] (amount >= 0 && amount <= 1000000) }
ltl safety_reentrancy { [] !(lock && amount > 100) }
ltl liveness_progress { <> (state == 2) }
ltl invariant_collateral { [] (user_collateral >= user_debt) }
ltl stability { [] (lock == false -> <> (amount > 0 && health_factor > 200)) }
ltl fairness { [] <> (lock == false) }

--- LTL safety_no_overflow ---
pan: ltl formula safety_no_overflow
State-vector 52 byte, depth reached 15, errors: 0
        7 states, stored
        8 transitions (= stored+matched)
pan: elapsed time 0 seconds

--- LTL safety_reentrancy ---
pan: ltl formula safety_reentrancy
State-vector 52 byte, depth reached 15, errors: 0
        7 states, stored
        8 transitions (= stored+matched)

--- LTL liveness_progress ---
pan: ltl formula liveness_progress
State-vector 52 byte, depth reached 15, errors: 0
        7 states, stored
        8 transitions (= stored+matched)

--- LTL invariant_collateral ---
pan: ltl formula invariant_collateral
State-vector 52 byte, depth reached 15, errors: 0
        7 states, stored
        8 transitions (= stored+matched)

--- LTL stability ---
pan: ltl formula stability
State-vector 52 byte, depth reached 15, errors: 1
        7 states, stored
        8 transitions (= stored+matched)
pan:1: acceptance cycle (at depth 14)
pan: wrote translated_output.pml.trail

--- LTL fairness ---
pan: ltl formula fairness
State-vector 52 byte, depth reached 15, errors: 0
        7 states, stored
        8 transitions (= stored+matched)
"""

    _CREUSOT_DEMO_OUTPUT = """\
Verification successful for defi_vault.rs
  [PASS] borrow_within_collateral
  [PASS] repay_clears_debt
  [PASS] withdraw_requires_zero_debt
  [PASS] deposit_increases_collateral
Why3 backend: all obligations discharged.
"""

    # Demo user
    demo = User.query.filter_by(username='demo').first()
    if not demo:
        demo = User(
            username='demo',
            email='demo@defiguardian.local',
            password_hash=generate_password_hash("demo1234"),
            role='user'
        )
        db.session.add(demo)
    else:
        demo.role = 'user'

    # Admin user
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@defiguardian.local',
            password_hash=generate_password_hash("admin1234"),
            role='admin'
        )
        db.session.add(admin)
    else:
        admin.role = 'admin'

    # Seed audit records if empty
    if AuditHistory.query.count() == 0:
        records = [
            # (filename, file_type, tool, status, states, trans, depth, output)
            ("SimpleLending.sol", ".sol", "SPIN",    "FAIL", 7, 8, 15, _SPIN_DEMO_OUTPUT),
            ("SimpleLending.sol", ".sol", "COQ",     "FAIL", 0, 0, 0, "Error: type mismatch in Theorem collateral_safety.\nCheck your Coq proof script."),
            ("SimpleLending.sol", ".sol", "LEAN",    "PASS", 0, 0, 0, "Verification successful\ntheorem borrow_safe : ..."),
            ("SimpleLending.sol", ".sol", "CERTORA", "FAIL", 0, 0, 0, "rule collateral_check - violated\ncounterexample found at step 3"),
            ("defi_vault.rs",     ".rs",  "KANI",    "PASS", 0, 0, 0, "VERIFICATION:- SUCCESSFUL\nCheck 1: no_overflow - SATISFIED"),
            ("defi_vault.rs",     ".rs",  "PRUSTI",  "PASS", 0, 0, 0, "Verification successful\nAll postconditions hold."),
            ("user_lending.rs",   ".rs",  "CREUSOT", "PASS", 0, 0, 0, _CREUSOT_DEMO_OUTPUT),
            ("user_lending.rs",   ".rs",  "VERUS",   "PASS", 0, 0, 0, "verification results:: 4 verified, 0 errors"),
        ]
        for fn, ft, tool, status, states, trans, depth, output in records:
            new_audit = AuditHistory(
                filename=fn,
                file_type=ft,
                tool_used=tool,
                status=status,
                states_explored=states,
                transitions=trans,
                depth_reached=depth,
                verification_output=output,
            )
            db.session.add(new_audit)

    db.session.commit()
