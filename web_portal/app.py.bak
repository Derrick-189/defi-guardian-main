"""
DeFi Guardian - Web Portal
Wraps existing functionality in a web interface with real-time data flow.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import sqlite3
import os
import sys
import re
import json
import threading
import subprocess
from pathlib import Path

# Add parent directory to path to import existing modules
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    # Fallback if __file__ is not defined
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath('.'))))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'defi_guardian.db')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
EXTERNAL_AUDIT_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'generated', 'reports', 'audit_log.json')

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ==================== DATABASE SETUP ====================

def init_db():
    """Initialize database tables"""
    conn = sqlite3.connect(app.config['DATABASE'])
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            organization TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Audit history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT NOT NULL,
            file_type TEXT,
            tool_used TEXT,
            status TEXT,
            states_explored INTEGER,
            transitions INTEGER,
            depth_reached INTEGER,
            vulnerabilities_found TEXT,
            ltl_properties TEXT,
            verification_output TEXT,
            audit_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            report_path TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Contact messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT 0
        )
    ''')
    
    # Service subscriptions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_date TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# ==================== USER MODEL ====================

class User(UserMixin):
    def __init__(self, id, username, email, role):
        self.id = id
        self.username = username
        self.email = email
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(app.config['DATABASE'])
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return User(user[0], user[1], user[2], user[3])
    return None

# ==================== AUDIT DATABASE HELPER ====================

def sync_external_audit_history():
    """Import desktop audit log entries into portal audit history."""
    if not os.path.exists(EXTERNAL_AUDIT_LOG_FILE):
        return False, "Audit log file not found."

    try:
        with open(EXTERNAL_AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
    except Exception as e:
        return False, f"Error reading audit log: {e}"

    try:
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        new_records = 0

        for job in jobs:
            filename = job.get('file', 'unknown')
            tool = job.get('tool', 'unknown')
            timestamp = job.get('timestamp', '')
            status = job.get('status', '').upper()
            if status in ('SUCCESS', 'PASSED'):
                status = 'PASS'
            elif status not in ('PASS', 'FAIL'):
                status = 'FAIL'

            cursor.execute('''
                SELECT 1 FROM audit_history
                WHERE filename = ? AND tool_used = ? AND audit_date = ?
            ''', (filename, tool, timestamp))
            if cursor.fetchone():
                continue

            log_path   = job.get('log_path', '')
            trace_path = job.get('trace_path', '')
            cursor.execute('''
                INSERT INTO audit_history (
                    user_id, filename, file_type, tool_used, status,
                    states_explored, transitions, depth_reached,
                    vulnerabilities_found, ltl_properties,
                    verification_output, audit_date, report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                current_user.id if current_user.is_authenticated else None,
                filename,
                os.path.splitext(filename)[1] or '',
                tool,
                status,
                job.get('details', {}).get('states', 0),
                job.get('details', {}).get('transitions', 0),
                job.get('details', {}).get('depth', 0),
                job.get('details', {}).get('error_msg', ''),
                json.dumps(job.get('specs', [])),
                log_path,
                timestamp,
                trace_path or log_path,
            ))
            new_records += 1

        conn.commit()
        return True, f"Successfully synced {new_records} new records."
    except Exception as e:
        return False, f"Database error during sync: {e}"
    finally:
        try:
            conn.close()
        except:
            pass

@app.route('/api/sync-audit', methods=['POST'])
@login_required
def trigger_sync():
    """Manually trigger synchronization of desktop audit logs."""
    success, message = sync_external_audit_history()
    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/set-theme', methods=['POST'])
def set_theme():
    """Set user's preferred theme in session."""
    data = request.json
    theme = data.get('theme', 'dark')
    session['theme'] = theme
    return jsonify({'status': 'success', 'theme': theme})

# Now that sync_external_audit_history is defined, run the initial sync
sync_external_audit_history()

class AuditDatabase:
    """Handle audit history operations"""
    
    @staticmethod
    def save_audit(user_id, filename, file_type, tool, status, stats, ltl_results, output, report_path):
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_history 
            (user_id, filename, file_type, tool_used, status, states_explored, 
             transitions, depth_reached, ltl_properties, verification_output, report_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, filename, file_type, tool, status,
            stats.get('states', 0), stats.get('transitions', 0),
            stats.get('depth', 0), json.dumps(ltl_results),
            output, report_path
        ))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_user_audits(user_id, limit=50):
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, filename, file_type, tool_used, status,
                   states_explored, transitions, depth_reached, vulnerabilities_found,
                   ltl_properties, verification_output, audit_date, report_path
            FROM audit_history
            WHERE user_id = ? OR user_id IS NULL
            ORDER BY audit_date DESC
            LIMIT ?
        ''', (user_id, limit))
        columns = ['id', 'user_id', 'filename', 'file_type', 'tool_used', 'status',
                   'states_explored', 'transitions', 'depth_reached', 'vulnerabilities_found',
                   'ltl_properties', 'verification_output', 'audit_date', 'report_path']
        audits = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return audits
    
    @staticmethod
    def get_public_audits(limit=20):
        """Get recent audits for public display (anonymized)"""
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        cursor.execute('''
            SELECT filename, file_type, tool_used, status, 
                   states_explored, depth_reached, audit_date
            FROM audit_history 
            ORDER BY audit_date DESC 
            LIMIT ?
        ''', (limit,))
        audits = cursor.fetchall()
        conn.close()
        return audits

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Homepage or redirect authenticated users to their dashboard"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    recent_audits = AuditDatabase.get_public_audits(5)
    return render_template('index.html', recent_audits=recent_audits)

@app.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@app.route('/services')
def services():
    """Services page"""
    plans = [
        {'name': 'Community', 'price': 'Free', 'features': ['Basic SPIN Verification', 'Up to 3 contracts/month']},
        {'name': 'Professional', 'price': '$49/month', 'features': ['Full Verification Suite', 'Rust verification']},
        {'name': 'Enterprise', 'price': 'Custom', 'features': ['Dedicated support', 'API access']}
    ]
    return render_template('services.html', plans=plans)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact page"""
    if request.method == 'POST':
        flash('Message sent successfully!', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page"""
    if request.method == 'POST':
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email, password_hash, role FROM users WHERE username = ?', (username,))
        user_data = cursor.fetchone()
        conn.close()
        if user_data and check_password_hash(user_data[3], password):
            user = User(user_data[0], user_data[1], user_data[2], user_data[4])
            login_user(user, remember=request.form.get('remember'))
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard with audit history"""
    audits = AuditDatabase.get_user_audits(current_user.id)
    return render_template('dashboard.html', audits=audits)

@app.route('/counterexample/<int:audit_id>')
@login_required
def counterexample_analysis(audit_id):
    """Counterexample analysis page"""
    return render_template('counterexample.html', audit_id=audit_id)

@app.route('/trace/<int:audit_id>')
@login_required
def trace_viewer(audit_id):
    """Trace viewer page"""
    return render_template('trace.html', audit_id=audit_id)

@app.route('/visualization')
@login_required
def visualization():
    """3D visualization and state graphs"""
    return render_template('visualization.html')

# ==================== API ENDPOINTS ====================

@app.route('/api/events/emit', methods=['POST'])
def emit_event():
    """Receive VerificationCompleteEvent from desktop app and broadcast via SocketIO."""
    try:
        event_data = request.get_json()
        if not event_data:
            return jsonify({'error': 'No data received'}), 400
        socketio.emit('verification_complete', event_data)
        return jsonify({'status': 'success', 'message': 'Event broadcasted'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/counterexample/<int:audit_id>')
@login_required
def get_counterexample(audit_id):
    """Get counterexample analysis for specific audit using TraceParser."""
    try:
        from trace_parsers import get_parser
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        cursor.execute('''
            SELECT verification_output, report_path, tool_used, filename, status, ltl_properties
            FROM audit_history WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''', (audit_id, current_user.id))
        result = cursor.fetchone()
        conn.close()

        if not result:
            return jsonify({'error': 'Audit not found'}), 404

        log_path, report_path, tool, filename, status, ltl_props_raw = result
        parser = get_parser(tool)
        if not parser:
            return jsonify({'error': f'No parser available for tool: {tool}'}), 500
            
        rules = parser.parse_rules(log_path)
        trace = parser.parse_trace(log_path, report_path)
        recommendations = parser.get_recommendations(status)
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        state_graph = _load_state_graph(project_dir)

        return jsonify({
            'audit_id': audit_id, 'tool': tool, 'tool_type': (tool or '').upper(),
            'filename': filename, 'status': status, 'ltl_properties': rules,
            'trace_data': trace.to_dict() if trace else None,
            'recommendations': recommendations, 'state_graph': state_graph,
            'output': trace.error_message if trace else "",
            'counterexample': [s.action for s in (trace.steps if trace else [])],
            'is_non_spin': (tool or '').upper() != 'SPIN'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trace/<int:audit_id>')
@login_required
def get_trace(audit_id):
    """Get execution trace for specific audit."""
    try:
        from trace_parsers import get_parser
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        cursor.execute('''
            SELECT report_path, verification_output, tool_used
            FROM audit_history WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''', (audit_id, current_user.id))
        result = cursor.fetchone()
        conn.close()

        if not result:
            return jsonify({'error': 'Audit not found'}), 404

        report_path, log_path, tool = result
        parser = get_parser(tool)
        if not parser:
            return jsonify({'error': f'No parser available for tool: {tool}'}), 500
            
        trace = parser.parse_trace(log_path, report_path)
        return jsonify({
            'trace': [s.to_dict() for s in (trace.steps if trace else [])],
            'final_variables': trace.final_variables if trace else {},
            'error_message': trace.error_message if trace else None,
            'tool': tool
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/state-graph/<int:audit_id>')
@login_required
def get_state_graph(audit_id):
    """Return state graph JSON for a given audit."""
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        state_graph = _load_state_graph(project_dir)
        if state_graph:
            return jsonify(state_graph)
        return jsonify({'error': 'State graph not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _load_state_graph(project_dir):
    """Load the most recent state graph JSON."""
    candidates = [
        os.path.join(project_dir, 'generated', 'reports', 'state_graph.json'),
        os.path.join(project_dir, 'verification_state.json'),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                continue
    return None

@app.route('/api/desktop-runs')
@login_required
def get_desktop_runs():
    """Return recent desktop audit runs from audit_log.json."""
    try:
        if not os.path.exists(EXTERNAL_AUDIT_LOG_FILE):
            return jsonify([])
        with open(EXTERNAL_AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            runs = json.load(f)
        return jsonify([{
            'id': r.get('id', ''), 'timestamp': r.get('timestamp', ''),
            'tool': r.get('tool', ''), 'file': r.get('file', ''),
            'status': r.get('status', ''), 'states': r.get('details', {}).get('states', 0),
            'depth': r.get('details', {}).get('depth', 0),
            'error_msg': r.get('details', {}).get('error_msg', ''),
        } for r in runs[:50]])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== CONTEXT PROCESSORS ====================

@app.context_processor
def inject_globals():
    return {
        'current_year': datetime.now().year,
        'app_name': 'DeFi Guardian',
        'app_version': '1.0.0'
    }

if __name__ == '__main__':
    socketio.run(app, debug=False, port=5000, use_reloader=False, allow_unsafe_werkzeug=True)
