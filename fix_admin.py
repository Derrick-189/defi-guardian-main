import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "web_portal"))

from web_portal.app import app, db
from web_portal.audit_db import User, init_db

with app.app_context():
    init_db(app)
    user = User.query.filter_by(username='demo').first()
    if user:
        user.role = 'admin'
        db.session.commit()
        print("Updated 'demo' user to admin role.")
    else:
        # Create it if it doesn't exist
        from werkzeug.security import generate_password_hash
        new_admin = User(
            username='demo',
            email='demo@defiguardian.local',
            password_hash=generate_password_hash("demo1234"),
            role='admin'
        )
        db.session.add(new_admin)
        db.session.commit()
        print("Created 'demo' user with admin role.")
