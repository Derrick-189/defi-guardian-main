import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

try:
    from web_portal.app import app
    from web_portal.audit_db import db, User, AuditHistory
except ImportError as e:
    print(f"Import Error: {e}")
    print(f"Current sys.path: {sys.path}")
    sys.exit(1)

def test_db():
    with app.app_context():
        print("Initializing DB...")
        # This will use the default SQLite URI from Config if DATABASE_URL is not set
        db.create_all()
        
        user_count = User.query.count()
        audit_count = AuditHistory.query.count()
        
        print(f"Success! Users: {user_count}, Audits: {audit_count}")
        
        # Check if demo data was seeded
        demo_user = User.query.filter_by(username='demo').first()
        if demo_user:
            print(f"Demo user found: {demo_user.email}")
        else:
            print("Demo user not found!")

if __name__ == "__main__":
    try:
        test_db()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
