import sqlite3
from pathlib import Path
from datetime import datetime

PORTAL_DIR = Path(__file__).parent
QUEUE_DB = PORTAL_DIR / "verification_queue.db"

def init_queue():
    """Initialize the queue database."""
    conn = sqlite3.connect(str(QUEUE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            tool TEXT NOT NULL,
            contract_path TEXT NOT NULL,
            spec_path TEXT,
            output_dir TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            result TEXT
        )
    """)
    conn.commit()
    conn.close()

def submit_job(job_id, tool, contract_path, spec_path, output_dir):
    """Submit a job to the queue."""
    init_queue()
    conn = sqlite3.connect(str(QUEUE_DB))
    conn.execute("""
        INSERT INTO jobs (job_id, tool, contract_path, spec_path, output_dir)
        VALUES (?, ?, ?, ?, ?)
    """, (job_id, tool, contract_path, spec_path, output_dir))
    conn.commit()
    conn.close()

def get_pending_job():
    """Get the next pending job."""
    conn = sqlite3.connect(str(QUEUE_DB))
    row = conn.execute("""
        SELECT * FROM jobs WHERE status = 'pending'
        ORDER BY created_at ASC LIMIT 1
    """).fetchone()
    if row:
        # Mark as running
        conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                    (datetime.now(), row[0]))
        conn.commit()
    conn.close()
    return row

def complete_job(job_id, result):
    """Mark a job as completed."""
    conn = sqlite3.connect(str(QUEUE_DB))
    conn.execute("""
        UPDATE jobs SET status = 'completed', completed_at = ?, result = ?
        WHERE job_id = ?
    """, (datetime.now(), str(result), job_id))
    conn.commit()
    conn.close()
