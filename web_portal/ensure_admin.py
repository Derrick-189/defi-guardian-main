import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from web_portal.app import app, db
from web_portal.audit_db import User, init_db
from werkzeug.security import generate_password_hash

def ensure_admin():
    with app.app_context():
        # init_db(app) # Removed as it is called in app.py during import
        
        # 1. Check/Update demo user
        demo = User.query.filter_by(username='demo').first()
        if demo:
            if demo.role != 'admin':
                demo.role = 'admin'
                db.session.commit()
                print(f"Updated user '{demo.username}' to admin role.")
            else:
                print(f"User '{demo.username}' is already an admin.")
        else:
            demo = User(
                username='demo',
                email='demo@defiguardian.local',
                password_hash=generate_password_hash("demo1234"),
                role='admin'
            )
            db.session.add(demo)
            db.session.commit()
            print(f"Created user '{demo.username}' with admin role.")

        # 2. Check/Create dedicated admin user
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@defiguardian.local',
                password_hash=generate_password_hash("admin1234"),
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()
            print(f"Created user '{admin.username}' with admin role.")
        else:
            if admin.role != 'admin':
                admin.role = 'admin'
                db.session.commit()
                print(f"Updated user '{admin.username}' to admin role.")
            else:
                print(f"User '{admin.username}' is already an admin.")

if __name__ == "__main__":
    ensure_admin()
