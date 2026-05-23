import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Accept both the legacy 'YYYY-MM-DD HH:MM:SS.ffffff' format SQLite stores
# and the now-standard 'YYYY-MM-DDTHH:MM:SS.ffffff' format.
def _parse_dt(val) -> datetime:
    if not val:
        return datetime.now(timezone.utc)
    s = str(val).strip().replace('Z', '+00:00')
    if 'T' in s:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)


def migrate(app=None, db=None, User=None, AuditHistory=None, ContactMessage=None):
    # 1. Check for source SQLite database
    # Assuming the default location if not specified
    root_dir = Path(__file__).parent.resolve()
    sqlite_path = root_dir / "web_portal" / "defi_guardian.db"
    
    if not sqlite_path.exists():
        print(f"Error: SQLite database not found at {sqlite_path}")
        return

    # If components are not provided, import them (this might cause circular imports if called from app.py)
    if app is None:
        # Add project root and web_portal to path
        sys.path.insert(0, str(root_dir))
        sys.path.insert(0, str(root_dir / "web_portal"))
        from web_portal.app import app as _app
        from web_portal.audit_db import db as _db, User as _User, AuditHistory as _AuditHistory, ContactMessage as _ContactMessage
        app, db, User, AuditHistory, ContactMessage = _app, _db, _User, _AuditHistory, _ContactMessage

    # 2. Connect to SQLite
    print(f"Connecting to SQLite: {sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    with app.app_context():
        # 3. Ensure Postgres tables exist
        print("Ensuring PostgreSQL tables exist...")
        db.create_all()

        # 4. Migrate Users
        print("Migrating Users...")
        try:
            rows = cursor.execute("SELECT * FROM users").fetchall()
            for row in rows:
                if not User.query.filter_by(username=row['username']).first():
                    user = User(
                        username=row['username'],
                        email=row['email'],
                        password_hash=row['password_hash'],
                        organization=row.get('organization'),
                        role=row.get('role', 'user'),
                        created_at=_parse_dt(row['created_at'])
                    )
                    db.session.add(user)
            db.session.commit()
            print(f"Migrated {len(rows)} users.")
        except Exception as e:
            print(f"User migration skipped or failed: {e}")

        # 5. Migrate Audit History
        print("Migrating Audit History...")
        try:
            rows = cursor.execute("SELECT * FROM audit_history").fetchall()
            for row in rows:
                # Check if already exists by filename + tool (won't match exact
                # audit_date across DB engines reliably, so use a broader dedup).
                exists = AuditHistory.query.filter(
                    AuditHistory.filename == row['filename'],
                    AuditHistory.tool_used  == row['tool_used'],
                ).filter(
                    AuditHistory.audit_date >= _parse_dt(row['audit_date']) - timedelta(seconds=1),
                    AuditHistory.audit_date <= _parse_dt(row['audit_date']) + timedelta(seconds=1),
                ).first()

                if not exists:
                    dt = _parse_dt(row['audit_date'])
                    audit = AuditHistory(
                        user_id=row['user_id'],
                        job_id=row['job_id'],
                        filename=row['filename'],
                        file_type=row['file_type'],
                        tool_used=row['tool_used'],
                        status=row['status'],
                        states_explored=row.get('states_explored', 0),
                        transitions=row.get('transitions', 0),
                        depth_reached=row.get('depth_reached', 0),
                        vulnerabilities_found=row.get('vulnerabilities_found'),
                        ltl_properties=row.get('ltl_properties'),
                        verification_output=row.get('verification_output'),
                        trace_data=row.get('trace_data'),
                        audit_date=dt,
                        report_path=row.get('report_path')
                    )
                    db.session.add(audit)
            db.session.commit()
            print(f"Migrated {len(rows)} audit records.")
        except Exception as e:
            print(f"Audit migration skipped or failed: {e}")

        # 6. Migrate Contact Messages
        print("Migrating Contact Messages...")
        try:
            rows = cursor.execute("SELECT * FROM contact_messages").fetchall()
            for row in rows:
                msg = ContactMessage(
                    name=row['name'],
                    email=row['email'],
                    subject=row.get('subject'),
                    message=row['message'],
                    created_at=_parse_dt(row['created_at']),
                    is_read=bool(int(row.get('is_read', 0)))
                )
                db.session.add(msg)
            db.session.commit()
            print(f"Migrated {len(rows)} contact messages.")
        except Exception as e:
            print(f"Contact message migration skipped or failed: {e}")

    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        print("Error: DATABASE_URL environment variable not set.")
        print("Please set it to your PostgreSQL connection string before running.")
        sys.exit(1)
    migrate()
