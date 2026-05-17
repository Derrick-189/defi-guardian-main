"""
DeFi Guardian — Audit Database helpers
Centralised SQLite access for the web portal.
Robust schema with auto-migration on startup.
"""
from __future__ import annotations
import sqlite3, os, json
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent.parent
AUDIT_LOG   = PROJECT_DIR / "generated" / "reports" / "audit_log.json"
DB_PATH     = Path(__file__).parent / "defi_guardian.db"


def get_db(path: str = str(DB_PATH)) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add missing columns to existing tables without dropping data."""
    cur = conn.cursor()
    
    # Get existing columns for audit_history
    existing = {row[1] for row in cur.execute("PRAGMA table_info(audit_history)")}
    
    additions = [
        ("job_id",            "TEXT"),
        ("trace_data",        "TEXT"),
        ("parsed_trace_json", "TEXT"),
        ("simulated",         "INTEGER DEFAULT 0"),
        ("specs_used",        "TEXT"),
        ("ltl_properties",    "TEXT"),
        ("vulnerabilities_found", "TEXT"),
        ("report_path",       "TEXT"),
    ]
    for col, typ in additions:
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE audit_history ADD COLUMN {col} {typ}")
            except Exception:
                pass

    conn.commit()


def init_db(path: str = str(DB_PATH)) -> None:
    conn = get_db(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            organization TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            job_id TEXT,
            filename TEXT NOT NULL,
            file_type TEXT,
            tool_used TEXT,
            status TEXT,
            states_explored INTEGER DEFAULT 0,
            transitions INTEGER DEFAULT 0,
            depth_reached INTEGER DEFAULT 0,
            vulnerabilities_found TEXT,
            ltl_properties TEXT,
            verification_output TEXT,
            trace_data TEXT,
            parsed_trace_json TEXT,
            simulated INTEGER DEFAULT 0,
            specs_used TEXT,
            audit_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            report_path TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_history(audit_date DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_job  ON audit_history(job_id);
    """)
    conn.commit()
    _migrate(conn)
    conn.close()


def sync_audit_log(db_path: str = str(DB_PATH)) -> int:
    """Import desktop audit_log.json into SQLite. Returns count of new rows."""
    if not AUDIT_LOG.exists():
        return 0
    try:
        jobs = json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
    except Exception:
        return 0

    conn = get_db(db_path)
    c = conn.cursor()
    new_count = 0
    for job in jobs:
        filename  = job.get("file", "unknown")
        tool      = job.get("tool", "unknown")
        timestamp = job.get("timestamp", "")
        raw       = job.get("status", "").upper()
        status    = "PASS" if raw in ("SUCCESS", "PASSED", "PASS") else "FAIL"

        if c.execute(
            "SELECT 1 FROM audit_history WHERE filename=? AND tool_used=? AND audit_date=?",
            (filename, tool, timestamp)
        ).fetchone():
            continue

        det = job.get("details", {})
        c.execute("""
            INSERT INTO audit_history
              (user_id,filename,file_type,tool_used,status,
               states_explored,transitions,depth_reached,
               vulnerabilities_found,ltl_properties,
               verification_output,audit_date,report_path,
               trace_data,simulated,specs_used)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            None, filename,
            os.path.splitext(filename)[1] or "",
            tool, status,
            det.get("states", 0), det.get("transitions", 0), det.get("depth", 0),
            det.get("error_msg", ""),
            json.dumps(job.get("specs", [])),
            job.get("log_path", ""),
            timestamp,
            job.get("trace_path", "") or job.get("log_path", ""),
            None,  # trace_data will be populated on demand
            0,
            json.dumps(job.get("specs", [])),
        ))
        new_count += 1

    conn.commit()
    conn.close()
    return new_count


def save_trace_data(db_path: str, audit_id: int, trace_data: dict) -> None:
    """Persist parsed trace JSON into audit_history for fast retrieval."""
    conn = get_db(db_path)
    conn.execute(
        "UPDATE audit_history SET trace_data=?, parsed_trace_json=? WHERE id=?",
        (json.dumps(trace_data), json.dumps(trace_data), audit_id)
    )
    conn.commit()
    conn.close()


def get_trace_data(db_path: str, audit_id: int) -> Optional[dict]:
    """Retrieve cached trace data from DB."""
    conn = get_db(db_path)
    row = conn.execute(
        "SELECT trace_data, parsed_trace_json FROM audit_history WHERE id=?",
        (audit_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    for col in ("parsed_trace_json", "trace_data"):
        val = row[col] if col in row.keys() else None
        if val:
            try:
                return json.loads(val)
            except Exception:
                pass
    return None


def get_user_audits(user_id: int, db_path: str = str(DB_PATH), limit: int = 100):
    conn = get_db(db_path)
    rows = conn.execute("""
        SELECT id,user_id,job_id,filename,file_type,tool_used,status,
               states_explored,transitions,depth_reached,
               vulnerabilities_found,ltl_properties,
               verification_output,audit_date,report_path,
               trace_data,simulated,specs_used
        FROM audit_history
        WHERE user_id=? OR user_id IS NULL
        ORDER BY audit_date DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_public_audits(db_path: str = str(DB_PATH), limit: int = 10):
    conn = get_db(db_path)
    rows = conn.execute("""
        SELECT filename,file_type,tool_used,status,
               states_explored,depth_reached,audit_date
        FROM audit_history ORDER BY audit_date DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def seed_demo_data(db_path: str = str(DB_PATH)) -> None:
    """Insert demo user + realistic audit records if DB is empty."""
    from werkzeug.security import generate_password_hash
    conn = get_db(db_path)
    c = conn.cursor()

    # Demo user
    if not c.execute("SELECT 1 FROM users WHERE username='demo'").fetchone():
        c.execute(
            "INSERT INTO users (username,email,password_hash,role) VALUES (?,?,?,?)",
            ("demo", "demo@defiguardian.local",
             generate_password_hash("demo1234"), "user")
        )

    # Seed audit records if empty
    if c.execute("SELECT COUNT(*) FROM audit_history").fetchone()[0] == 0:
        records = [
            ("SimpleLending.sol", ".sol", "SPIN",    "FAIL", 7, 8, 15),
            ("SimpleLending.sol", ".sol", "COQ",     "FAIL", 0, 0, 0),
            ("SimpleLending.sol", ".sol", "LEAN",    "PASS", 0, 0, 0),
            ("SimpleLending.sol", ".sol", "CERTORA", "FAIL", 0, 0, 0),
            ("defi_vault.rs",     ".rs",  "KANI",    "PASS", 0, 0, 0),
            ("defi_vault.rs",     ".rs",  "PRUSTI",  "PASS", 0, 0, 0),
            ("user_lending.rs",   ".rs",  "CREUSOT", "PASS", 0, 0, 0),
            ("user_lending.rs",   ".rs",  "VERUS",   "PASS", 0, 0, 0),
        ]
        for fn, ft, tool, status, states, trans, depth in records:
            c.execute("""
                INSERT INTO audit_history
                  (filename,file_type,tool_used,status,
                   states_explored,transitions,depth_reached,simulated)
                VALUES (?,?,?,?,?,?,?,1)
            """, (fn, ft, tool, status, states, trans, depth))

    conn.commit()
    conn.close()
