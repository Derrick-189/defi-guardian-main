from app import app, db
from audit_db import User

with app.app_context():
    user = User.query.filter_by(username='demo').first()
    if user:
        user.role = 'admin'
        db.session.commit()
        print("Updated 'demo' user to admin role.")
    else:
        print("User 'demo' not found.")
