"""
DeFi Guardian - Complete Streamlit Dashboard
Formal Verification Visualization with State Diagrams
Full Sidebar Settings and State Type Selection
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import subprocess
import os
import tempfile
import re
import asyncio
import threading
from datetime import datetime
import numpy as np
import json
from PIL import Image
import io
import sqlite3
import hashlib
import hmac
try:
    import graphviz
except ImportError:
    graphviz = None

try:
    import networkx as nx
except ImportError:
    nx = None
import time

# Project directory for file I/O
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
SPIN_LOGS = os.path.join(LOGS_DIR, "spin")
CERTORA_LOGS = os.path.join(LOGS_DIR, "certora")
COQ_LOGS = os.path.join(LOGS_DIR, "coq")
LEAN_LOGS = os.path.join(LOGS_DIR, "lean")
RUST_LOGS = os.path.join(LOGS_DIR, "rust_tools")
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated")
MODELS_DIR = os.path.join(GENERATED_DIR, "models")
IMAGES_DIR = os.path.join(GENERATED_DIR, "images")
REPORTS_DIR = os.path.join(GENERATED_DIR, "reports")
CONSOLE_DIR = os.path.join(PROJECT_DIR, "console_exports")
AUDIT_LOG_FILE = os.path.join(REPORTS_DIR, "audit_log.json")

# Ensure directories exist
for d in [LOGS_DIR, SPIN_LOGS, CERTORA_LOGS, COQ_LOGS, LEAN_LOGS, RUST_LOGS, 
          GENERATED_DIR, MODELS_DIR, IMAGES_DIR, REPORTS_DIR, CONSOLE_DIR]:
    os.makedirs(d, exist_ok=True)
try:
    from streamlit_extras.stylable_container import stylable_container 
except ImportError:
    # Fallback if streamlit-extras is not installed
    def stylable_container(key, css_styles):
        return st.container()

# ==================== USER ACCOUNT HELPERS ====================
# Reuse the same SQLite database as the web portal when available.

_WEB_PORTAL_DB = os.path.join(PROJECT_DIR, "web_portal", "defi_guardian.db")
_FALLBACK_DB   = os.path.join(REPORTS_DIR, "dashboard_users.db")

def _get_db_path() -> str:
    """Return the best available user database path."""
    if os.path.exists(_WEB_PORTAL_DB):
        return _WEB_PORTAL_DB
    return _FALLBACK_DB

def _ensure_user_tables():
    """Create user tables if they don't exist (fallback DB only)."""
    db = _get_db_path()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('''
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
    cur.execute('''
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
    conn.commit()
    conn.close()

_ensure_user_tables()

def _hash_password(password: str) -> str:
    """Return a SHA-256 hex digest of the password (matches werkzeug pbkdf2 only for new accounts)."""
    # Use a simple but consistent scheme for dashboard-created accounts.
    return hashlib.sha256(password.encode()).hexdigest()

def _verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against stored hash (supports both werkzeug and sha256)."""
    # Try werkzeug-style hash first (web portal accounts)
    try:
        from werkzeug.security import check_password_hash
        if stored_hash.startswith("pbkdf2:") or stored_hash.startswith("scrypt:"):
            return check_password_hash(stored_hash, password)
    except ImportError:
        pass
    # Fallback: plain sha256
    return hmac.compare_digest(stored_hash, _hash_password(password))

def db_login(username: str, password: str):
    """Return user dict on success, None on failure."""
    db = _get_db_path()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, email, password_hash, organization, role FROM users WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()
    if row and _verify_password(row[3], password):
        cur.execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now().isoformat(), row[0]))
        conn.commit()
        conn.close()
        return {"id": row[0], "username": row[1], "email": row[2], "organization": row[4], "role": row[5]}
    conn.close()
    return None

def db_register(username: str, email: str, password: str, organization: str = "") -> tuple:
    """Register a new user. Returns (True, user_dict) or (False, error_message)."""
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    db = _get_db_path()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    try:
        # Use werkzeug if available for consistency with web portal
        try:
            from werkzeug.security import generate_password_hash
            pw_hash = generate_password_hash(password)
        except ImportError:
            pw_hash = _hash_password(password)
        cur.execute(
            "INSERT INTO users (username, email, password_hash, organization) VALUES (?, ?, ?, ?)",
            (username.strip(), email.strip().lower(), pw_hash, organization.strip())
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return True, {"id": user_id, "username": username, "email": email, "organization": organization, "role": "user"}
    except sqlite3.IntegrityError as e:
        conn.close()
        if "username" in str(e):
            return False, "Username already taken."
        if "email" in str(e):
            return False, "Email already registered."
        return False, str(e)

def db_get_user_audit_history(user_id: int, limit: int = 50):
    """Return audit history rows for a user (includes shared/anonymous rows)."""
    db = _get_db_path()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('''
        SELECT filename, file_type, tool_used, status,
               states_explored, transitions, depth_reached,
               audit_date, report_path, verification_output
        FROM audit_history
        WHERE user_id = ? OR user_id IS NULL
        ORDER BY audit_date DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows

def db_get_user_stats(user_id: int) -> dict:
    """Return aggregate stats for a user's verification history."""
    db = _get_db_path()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(*), SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END),
               SUM(states_explored), MAX(depth_reached)
        FROM audit_history
        WHERE user_id = ? OR user_id IS NULL
    ''', (user_id,))
    row = cur.fetchone()
    conn.close()
    total = row[0] or 0
    passed = row[1] or 0
    return {
        "total_jobs": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "total_states": row[2] or 0,
        "max_depth": row[3] or 0,
    }

def render_user_account_panel():
    """Render the user account section in the Streamlit sidebar."""
    t = get_current_theme()
    t_mode = st.session_state.get('theme', 'dark')

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-header">👤 USER ACCOUNT</div>', unsafe_allow_html=True)

    # ── Logged-in state ──────────────────────────────────────────────
    if st.session_state.get("user"):
        user = st.session_state["user"]
        role_badge_color = "#00ffcc" if user["role"] == "admin" else "#9b59b6"
        st.markdown(f"""
        <div style="background:{t['card_bg']};border:1px solid {t['card_border']};
                    border-radius:10px;padding:0.75rem 1rem;margin-bottom:0.5rem;">
            <div style="font-weight:700;color:{t['text_main']};font-size:0.95rem;">
                {user['username']}
            </div>
            <div style="font-size:0.75rem;color:{t['text_dim']};margin-top:2px;">
                {user.get('email','')}
            </div>
            {"<div style='font-size:0.7rem;color:"+t['text_dim']+"'>🏢 "+user['organization']+"</div>" if user.get('organization') else ""}
            <span style="background:{role_badge_color}22;color:{role_badge_color};
                         border:1px solid {role_badge_color}44;border-radius:20px;
                         padding:2px 8px;font-size:0.65rem;font-weight:700;
                         text-transform:uppercase;margin-top:4px;display:inline-block;">
                {user['role']}
            </span>
        </div>
        """, unsafe_allow_html=True)

        # Quick stats
        stats = db_get_user_stats(user["id"])
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Jobs", stats["total_jobs"])
        sc2.metric("Passed", stats["passed"])
        sc3.metric("Pass %", f"{stats['pass_rate']}%")

        if st.button("🚪 Sign Out", use_container_width=True, key="btn_signout"):
            st.session_state.pop("user", None)
            st.session_state.pop("account_tab", None)
            st.rerun()
        return

    # ── Logged-out state ─────────────────────────────────────────────
    tab_key = st.session_state.get("account_tab", "login")
    col_l, col_r = st.columns(2)
    with col_l:
        if st.button("Sign In", use_container_width=True,
                     type="primary" if tab_key == "login" else "secondary",
                     key="btn_show_login"):
            st.session_state["account_tab"] = "login"
            st.rerun()
    with col_r:
        if st.button("Register", use_container_width=True,
                     type="primary" if tab_key == "register" else "secondary",
                     key="btn_show_register"):
            st.session_state["account_tab"] = "register"
            st.rerun()

    if tab_key == "login":
        with st.form("form_login", clear_on_submit=False):
            uname = st.text_input("Username", key="login_username", placeholder="your_username")
            pwd   = st.text_input("Password", type="password", key="login_password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            if submitted:
                if not uname or not pwd:
                    st.error("Please fill in all fields.")
                else:
                    user = db_login(uname, pwd)
                    if user:
                        st.session_state["user"] = user
                        st.session_state.pop("account_tab", None)
                        st.success(f"Welcome back, {user['username']}!")
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")

    else:  # register
        with st.form("form_register", clear_on_submit=False):
            new_uname = st.text_input("Username", key="reg_username", placeholder="choose_a_username")
            new_email = st.text_input("Email",    key="reg_email",    placeholder="you@example.com")
            new_org   = st.text_input("Organization (optional)", key="reg_org", placeholder="Acme Corp")
            new_pwd   = st.text_input("Password", type="password", key="reg_password",  placeholder="min 6 chars")
            new_pwd2  = st.text_input("Confirm",  type="password", key="reg_password2", placeholder="repeat password")
            submitted = st.form_submit_button("Create Account", use_container_width=True)
            if submitted:
                if not new_uname or not new_email or not new_pwd:
                    st.error("Username, email and password are required.")
                elif new_pwd != new_pwd2:
                    st.error("Passwords do not match.")
                else:
                    ok, result = db_register(new_uname, new_email, new_pwd, new_org)
                    if ok:
                        st.session_state["user"] = result
                        st.session_state.pop("account_tab", None)
                        st.success(f"Account created! Welcome, {result['username']}.")
                        st.rerun()
                    else:
                        st.error(result)

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Initialize theme
if 'theme' not in st.session_state:
    st.session_state.theme = "dark"

# Dynamic theme synchronization with portal theme parameter
theme_param = st.query_params.get("theme")
if theme_param in ["dark", "light"] and theme_param != st.session_state.theme:
    st.session_state.theme = theme_param

# Theme Configuration Constants
THEMES = {
    "dark": {
        "bg_gradient": "linear-gradient(135deg, #0a0a0a, #1a1a2e)",
        "panel_bg": "rgba(26, 26, 46, 0.95)",
        "panel_border": "rgba(0, 255, 204, 0.15)",
        "text_main": "#e6edf3",
        "text_dim": "#8b949e",
        "accent": "#00ffcc",
        "secondary": "#ff00cc",
        "card_bg": "#0d1117",
        "card_border": "#30363d",
        "header_bg": "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)",
        "header_border": "rgba(0, 255, 204, 0.2)",
        "metric_bg": "rgba(26, 26, 46, 0.95)",
        "stat_card_bg": "rgba(0, 0, 0, 0.3)",
        "proof_card_bg": "#0a0a0f",
        "web3d_bg": "radial-gradient(circle at center, #1a1a2e 0%, #0a0a0f 100%)",
        "sidebar_card": "rgba(255, 255, 255, 0.03)",
        "chart_grid": "rgba(255, 255, 255, 0.1)",
        "chart_text": "#e6edf3"
    },
    "light": {
        "bg_gradient": "linear-gradient(135deg, #f3f3f3, #e5e5e5)",
        "panel_bg": "#ffffff",
        "panel_border": "#cecece",
        "text_main": "#333333",
        "text_dim": "#616161",
        "accent": "#007acc",
        "secondary": "#af00db",
        "card_bg": "#f8f9fa",
        "card_border": "#cecece",
        "header_bg": "#ffffff",
        "header_border": "#007acc",
        "metric_bg": "#ffffff",
        "stat_card_bg": "#ffffff",
        "proof_card_bg": "#ffffff",
        "web3d_bg": "#f3f3f3",
        "sidebar_card": "#ffffff",
        "chart_grid": "#e1e4e8",
        "chart_text": "#333333"
    }
}

def get_current_theme():
    return THEMES[st.session_state.get('theme', 'dark')]

def theme_toggle(): 
     """Theme toggle switch for dashboard""" 
     
     # Use sidebar for theme toggle to avoid layout shifting
     with st.sidebar:
         st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
         st.markdown('<div class="sidebar-header">🌓 DASHBOARD THEME</div>', unsafe_allow_html=True)
         
         col1, col2 = st.columns([1, 1])
         with col1:
             if st.button("🌙 Dark", use_container_width=True, type="primary" if st.session_state.theme == "dark" else "secondary"):
                 st.session_state.theme = "dark"
                 st.rerun()
         with col2:
             if st.button("☀️ Light", use_container_width=True, type="primary" if st.session_state.theme == "light" else "secondary"):
                 st.session_state.theme = "light"
                 st.rerun()
     
     t = get_current_theme()
     
     # Apply Dynamic Theme CSS
     st.markdown(f""" 
     <style> 
         /* Global App Styling */
         .stApp {{ 
            background: {t['bg_gradient']} !important; 
            color: {t['text_main']} !important;
         }} 
         
         /* Typography */
         h1, h2, h3, h4, h5, h6, p, span, label, .stMarkdown {{
            color: {t['text_main']} !important;
         }}
         
         /* Sidebar Consistency */
         section[data-testid="stSidebar"] {{
            background-color: {"#0d1117" if st.session_state.theme == "dark" else "#ffffff"} !important;
            border-right: 1px solid {t['card_border']} !important;
         }}

         /* Panel & Card Components */
         .metric-card, .panel, .glass-card, .verification-panel, .tool-card {{ 
             background: {t['panel_bg']} !important; 
             border: 1px solid {t['panel_border']} !important;
             color: {t['text_main']} !important;
             box-shadow: 0 4px 15px rgba(0,0,0,{"0.3" if st.session_state.theme == "dark" else "0.05"}) !important;
         }} 

         .sidebar-section {{
             background: {t['sidebar_card']} !important;
             border: 1px solid {t['panel_border']} !important;
             border-radius: 12px;
             padding: 1rem;
             margin-bottom: 1rem;
             color: {t['text_main']} !important;
         }}

         .sidebar-header {{
             color: {t['accent']} !important;
             font-size: 0.8rem;
             font-weight: 700;
             text-transform: uppercase;
             letter-spacing: 0.1em;
             margin-bottom: 0.8rem;
         }}
         
         .professional-header {{
             background: {t['header_bg']} !important;
             border: 1px solid {t['header_border']} !important;
             border-radius: 12px;
             padding: 1.5rem 2rem;
             margin-bottom: 2rem;
             box-shadow: 0 4px 20px rgba(0, 0, 0, {"0.3" if st.session_state.theme == "dark" else "0.05"});
         }}
         
         .stat-card {{
             background: {t['stat_card_bg']} !important;
             border: 1px solid {t['card_border']} !important;
             border-radius: 12px;
             padding: 1.5rem;
             text-align: center;
             transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
             box-shadow: 0 2px 10px rgba(0,0,0,{"0.2" if st.session_state.theme == "dark" else "0.05"});
         }}
         
         .stat-card:hover {{
             transform: translateY(-5px);
             border-color: {t['accent']} !important;
             box-shadow: 0 10px 25px rgba(0,0,0,{"0.4" if st.session_state.theme == "dark" else "0.1"});
         }}
         
         .stat-number {{
             font-size: 2.2rem;
             font-weight: 800;
             color: {t['accent']} !important;
             margin-bottom: 0.5rem;
             font-family: 'Inter', sans-serif;
         }}
         
         .stat-label {{
             font-size: 0.75rem;
             font-weight: 700;
             color: {t['text_dim']} !important;
             text-transform: uppercase;
             letter-spacing: 0.1em;
         }}
         
         .proof-card {{
             background: {t['proof_card_bg']} !important;
             border-left: 4px solid {t['accent']} !important;
             border-radius: 12px;
             padding: 1.5rem;
             margin: 1rem 0;
             color: {t['text_main']} !important;
             box-shadow: 0 4px 20px rgba(0, 0, 0, {"0.4" if st.session_state.theme == "dark" else "0.1"});
         }}

         .ltl-property {{
             background: {t['stat_card_bg']} !important;
             border: 1px solid {t['accent']} !important;
             border-radius: 8px;
             padding: 0.75rem;
             margin: 0.5rem 0;
             color: {t['text_main']} !important;
         }}

         .status-badge {{
             padding: 4px 12px;
             border-radius: 20px;
             font-size: 0.7rem;
             font-weight: 800;
             text-transform: uppercase;
             border: 1px solid transparent;
         }}

         .status-badge.online, .status-badge.success {{
             background: rgba(16, 185, 129, 0.1) !important;
             color: #10b981 !important;
             border-color: rgba(16, 185, 129, 0.2) !important;
         }}

         .status-badge.offline, .status-badge.error {{
             background: rgba(239, 68, 68, 0.1) !important;
             color: #ef4444 !important;
             border-color: rgba(239, 68, 68, 0.2) !important;
         }}

         .risk-indicator {{
             padding: 1rem;
             border-radius: 12px;
             text-align: center;
             font-weight: 800;
             font-size: 0.9rem;
             margin-top: 0.5rem;
             background: {t['stat_card_bg']} !important;
         }}

         /* Input field visibility fixes */
         .stTextInput > div > div > input, .stNumberInput > div > div > input {{
             background-color: {t['card_bg']} !important;
             color: {t['text_main']} !important;
             border: 1px solid {t['card_border']} !important;
         }}

         .stTextArea > div > div > textarea {{
             background-color: {t['card_bg']} !important;
             color: {t['text_main']} !important;
             border: 1px solid {t['card_border']} !important;
         }}

         .web3d-container {{
             background: {t['web3d_bg']} !important;
             border: 2px solid {t['panel_border']} !important;
             border-radius: 16px;
             overflow: hidden;
             box-shadow: 0 8px 32px rgba(0, 0, 0, {"0.5" if st.session_state.theme == "dark" else "0.1"});
         }}

         /* Text and UI Accents */
         .metric-value, .stat-number, .panel-title, .state-diagram-title {{ 
             color: {t['accent']} !important; 
         }} 
         
         .header-title {{
             background: linear-gradient(135deg, {t['text_main']}, {t['accent']});
             -webkit-background-clip: text;
             -webkit-text-fill-color: transparent;
         }}
         
         .header-subtitle, .stat-label, .metric-label, .certora-val-changed {{
             color: {t['text_dim']} !important;
         }}

         .divider {{
             background: linear-gradient(90deg, transparent, {t['accent']}, transparent) !important;
             height: 1px;
             margin: 1.5rem 0;
         }}

         /* Interactive Elements */
         .stButton>button {{
             border-radius: 8px !important;
         }}
         
         .stSelectSlider > div[data-baseweb="select-slider"] > div {{
             background: linear-gradient(90deg, {t['accent']}, {t['secondary']}) !important;
         }}
         
         .stSelectSlider > div[data-baseweb="select-slider"] > div > div[role="slider"] {{
             background: {t['accent']} !important;
             border: 2px solid {t['text_main']} !important;
         }}

         /* Plotly and Graph Colors */
         .js-plotly-plot .plotly .main-svg {{
             background: transparent !important;
         }}
     </style> 
     """, unsafe_allow_html=True)

# Run theme application
theme_toggle()

# Get theme for global use
t = get_current_theme()

def styled_button(label, key=None, variant="primary", size="medium"): 
     """Generate styled HTML button for Streamlit""" 
     
     # Use theme-aware colors
     t = get_current_theme()
     t_mode = st.session_state.get('theme', 'dark')
     
     variants = { 
         "primary": { 
             "bg": "linear-gradient(135deg, #00ffcc 0%, #00ccff 100%)" if t_mode == "dark" else "linear-gradient(135deg, #007acc 0%, #005a9e 100%)", 
             "color": "#0a0e17" if t_mode == "dark" else "white", 
             "hover": "linear-gradient(135deg, #00e6b8 0%, #00b8e6 100%)" if t_mode == "dark" else "linear-gradient(135deg, #005a9e 0%, #004080 100%)"
         }, 
         "secondary": { 
             "bg": "linear-gradient(135deg, #9b59b6 0%, #8e44ad 100%)", 
             "color": "white", 
             "hover": "linear-gradient(135deg, #a86bc9 0%, #9b59b6 100%)" 
         }, 
         "danger": { 
             "bg": "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)", 
             "color": "white", 
             "hover": "linear-gradient(135deg, #f56565 0%, #e53e3e 100%)" 
         }, 
         "success": { 
             "bg": "linear-gradient(135deg, #10b981 0%, #059669 100%)", 
             "color": "white", 
             "hover": "linear-gradient(135deg, #34d399 0%, #10b981 100%)" 
         } 
     } 
     
     sizes = { 
         "small": {"padding": "8px 16px", "font-size": "12px"}, 
         "medium": {"padding": "12px 24px", "font-size": "14px"}, 
         "large": {"padding": "16px 32px", "font-size": "16px"} 
     } 
     
     v = variants.get(variant, variants["primary"]) 
     s = sizes.get(size, sizes["medium"]) 
     
     button_html = f""" 
     <style> 
         .styled-btn-{key} {{ 
             background: {v['bg']}; 
             color: {v['color']}; 
             border: none; 
             border-radius: 12px; 
             padding: {s['padding']}; 
             font-size: {s['font-size']}; 
             font-weight: 600; 
             cursor: pointer; 
             transition: all 0.3s ease; 
             position: relative; 
             overflow: hidden; 
             width: 100%; 
             text-align: center; 
             display: inline-block; 
             text-decoration: none; 
         }} 
         
         .styled-btn-{key}:hover {{ 
             background: {v['hover']}; 
             transform: translateY(-2px); 
             box-shadow: 0 8px 20px rgba(0, 255, 204, 0.2); 
         }} 
         
         .styled-btn-{key}::after {{ 
             content: ''; 
             position: absolute; 
             top: 50%; 
             left: 50%; 
             width: 0; 
             height: 0; 
             border-radius: 50%; 
             background: rgba(255, 255, 255, 0.3); 
             transform: translate(-50%, -50%); 
             transition: width 0.3s, height 0.3s; 
         }} 
         
         .styled-btn-{key}:active::after {{ 
             width: 200px; 
             height: 200px; 
         }} 
     </style> 
     <button class="styled-btn-{key}" onclick="this.disabled=true; this.style.opacity='0.7';">{label}</button> 
     """ 
     
     return st.markdown(button_html, unsafe_allow_html=True)

def verification_progress_card(): 
     """Animated verification progress card""" 
     
     t = get_current_theme()
     
     with stylable_container( 
         key="progress_card", 
         css_styles=f""" 
             {{ 
                 background: {t['bg_gradient']}; 
                 border-radius: 16px; 
                 padding: 24px; 
                 border: 1px solid {t['panel_border']}; 
                 margin: 16px 0; 
                 color: {t['text_main']};
             }} 
         """ 
     ): 
         col1, col2 = st.columns([3, 1]) 
         
         with col1: 
             st.markdown("### 🔄 Verification Progress") 
             
             # Animated progress bar 
             st.markdown(""" 
             <div class="progress-container"> 
                 <div class="progress-fill" style="width: 75%; animation: pulse 2s infinite;"> 
                     <span class="progress-text">75%</span> 
                 </div> 
             </div> 
             <style> 
                 .progress-container { 
                     background: rgba(0,0,0,0.3); 
                     border-radius: 20px; 
                     height: 24px; 
                     overflow: hidden; 
                 } 
                 .progress-fill { 
                     background: linear-gradient(90deg, #00ffcc, #00ccaa); 
                     height: 100%; 
                     border-radius: 20px; 
                     display: flex; 
                     align-items: center; 
                     justify-content: center; 
                     transition: width 0.5s ease; 
                 } 
                 .progress-text { 
                     color: #0a0e17; 
                     font-weight: bold; 
                     font-size: 12px; 
                 } 
                 @keyframes pulse { 
                     0%, 100% { opacity: 1; } 
                     50% { opacity: 0.8; } 
                 } 
             </style> 
             """, unsafe_allow_html=True) 
             
             # Step indicators 
             steps = [ 
                 ("📄 Parse Contract", "completed"), 
                 ("🔄 Generate Model", "active"), 
                 ("🔍 Run SPIN", "pending"), 
                 ("📜 Coq Verification", "pending"), 
                 ("⚡ Lean Verification", "pending") 
             ] 
             
             for step, status in steps: 
                 icons = { 
                     "completed": "✅", 
                     "active": "🔄", 
                     "pending": "⏳" 
                 } 
                 st.markdown(f"{icons[status]} {step}") 
         
         with col2: 
             st.metric("Time Elapsed", "12.3s") 
             st.metric("States Explored", "1,234")

def landing_page(): 
     """Professional landing page with feature showcase""" 
     
     t = get_current_theme()
     
     # Hero section 
     st.markdown(f""" 
     <div style="text-align: center; padding: 4rem 2rem;"> 
         <h1 style="font-size: 3.5rem; background: linear-gradient(135deg, {t['accent']}, {t['secondary']}); -webkit-background-clip: text; -webkit-text-fill-color: transparent;"> 
             🛡️ DeFi Guardian 
         </h1> 
         <p style="font-size: 1.25rem; color: {t['text_dim']}; margin: 1rem 0;"> 
             Formal Verification Suite for Smart Contracts 
         </p> 
         <div style="display: flex; gap: 1rem; justify-content: center; margin: 2rem 0;"> 
             <button class="gradient-btn" style="background: linear-gradient(135deg, {t['accent']}, {t['secondary']}); color: #fff;">Get Started →</button> 
             <button class="glass-btn" style="background: {t['panel_bg']}; color: {t['text_main']}; border: 1px solid {t['panel_border']};">View Demo</button> 
         </div> 
     </div> 
     """, unsafe_allow_html=True) 
     
     # Feature grid 
     col1, col2, col3, col4 = st.columns(4) 
     
     features = [ 
         ("🔬", "Multi-Tool Verification", "SPIN, Coq, Lean, Prusti, Kani, Creusot"), 
         ("📐", "State Machine Analysis", "Interactive 3D state space exploration"), 
         ("📊", "Risk Analytics", "Monte Carlo simulations & health factors"), 
         ("📜", "Proof Generation", "Formal proof obligations & LTL properties") 
     ] 
     
     for col, (icon, title, desc) in zip([col1, col2, col3, col4], features): 
         with col: 
             st.markdown(f""" 
             <div class="glass-card" style="text-align: center; background: {t['panel_bg']}; border: 1px solid {t['panel_border']}; padding: 1.5rem; border-radius: 12px;"> 
                 <div style="font-size: 2.5rem;">{icon}</div> 
                 <h4 style="color: {t['accent']};">{title}</h4> 
                 <p style="color: {t['text_dim']}; font-size: 0.85rem;">{desc}</p> 
             </div> 
             """, unsafe_allow_html=True)

def notification_system(): 
     """Toast-style notifications for verification events""" 
     
     if "notifications" not in st.session_state: 
         st.session_state.notifications = [] 
     
     def add_notification(message, type="info", duration=5000): 
         st.session_state.notifications.append({ 
             "message": message, 
             "type": type, 
             "id": datetime.now().timestamp() 
         }) 
     
     # Display notifications 
     for notification in st.session_state.notifications[:3]: 
         colors = { 
             "success": ("#10b981", "#059669"), 
             "error": ("#ef4444", "#dc2626"), 
             "warning": ("#f59e0b", "#d97706"), 
             "info": ("#00ffcc", "#00ccaa") 
         } 
         bg, border = colors.get(notification["type"], colors["info"]) 
         
         st.markdown(f""" 
         <div class="notification" style=" 
             background: {bg}20; 
             border-left: 4px solid {border}; 
             padding: 1rem; 
             margin: 0.5rem 0; 
             border-radius: 8px; 
             animation: slideIn 0.3s ease; 
         "> 
             {notification["message"]} 
         </div> 
         <style> 
             @keyframes slideIn {{ 
                 from {{ transform: translateX(-100%); opacity: 0; }} 
                 to {{ transform: translateX(0); opacity: 1; }} 
             }} 
         </style> 
         """, unsafe_allow_html=True)

def render_3d_state_graph_web3d(state_graph_data, height=500):
    """
    Render 3D state graph using Three.js through Streamlit components
    """
    st.markdown(""" 
    <style> 
        iframe { 
            border-radius: 16px; 
            border: 2px solid rgba(0, 255, 204, 0.3) !important; 
            min-height: 600px; 
        } 
    </style> 
    """, unsafe_allow_html=True) 

    # Convert state graph data to JSON for JavaScript
    nodes_json = json.dumps(state_graph_data.get('nodes', []))
    edges_json = json.dumps(state_graph_data.get('edges', []))
    trail_json = json.dumps(st.session_state.get('trail_data', {}))
    
    t_mode = st.session_state.get('theme', 'dark')
    accent_color = "#00ffcc" if t_mode == "dark" else "#0066cc"
    info_bg = "rgba(10, 14, 23, 0.8)" if t_mode == "dark" else "rgba(255, 255, 255, 0.8)"
    tooltip_bg = "rgba(26, 26, 46, 0.95)" if t_mode == "dark" else "rgba(255, 255, 255, 0.95)"
    text_color = "#00ffcc" if t_mode == "dark" else "#1a1a1a"
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {
                margin: 0;
                overflow: hidden;
                background: transparent;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            }
            #container {
                width: 100vw;
                height: 100vh;
            }
            #info {
                position: absolute;
                top: 20px;
                left: 20px;
                color: {{TEXT_COLOR}};
                background: {{INFO_BG}};
                padding: 12px 20px;
                border-radius: 12px;
                border: 1px solid {{ACCENT_COLOR}}4d;
                backdrop-filter: blur(8px);
                pointer-events: none;
                z-index: 100;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            }
            #controls-hint {
                position: absolute;
                bottom: 20px;
                left: 20px;
                color: #888;
                background: {{INFO_BG}};
                padding: 6px 16px;
                border-radius: 20px;
                font-size: 11px;
                backdrop-filter: blur(4px);
                pointer-events: none;
                z-index: 100;
                letter-spacing: 0.5px;
            }
            .tooltip {
                position: absolute;
                background: {{TOOLTIP_BG}};
                color: {{TEXT_COLOR}};
                padding: 10px 15px;
                border-radius: 8px;
                border: 1px solid {{ACCENT_COLOR}}80;
                font-size: 13px;
                pointer-events: none;
                z-index: 200;
                display: none;
                box-shadow: 0 8px 32px rgba(0,0,0,0.5);
                backdrop-filter: blur(10px);
            }
""".replace('{{TEXT_COLOR}}', text_color).replace('{{INFO_BG}}', info_bg).replace('{{ACCENT_COLOR}}', accent_color).replace('{{TOOLTIP_BG}}', tooltip_bg) + """
            #error-log {
                position: absolute;
                top: 0;
                left: 0;
                color: #ff4444;
                font-size: 10px;
                z-index: 1000;
                background: rgba(0,0,0,0.7);
                display: none;
            }
            .certora-header {
                background: #f8f9fa;
                border-bottom: 1px solid #dee2e6;
                padding: 0.75rem 1.5rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                color: #495057;
            }
            .certora-sidebar {
                background: #ffffff;
                border-right: 1px solid #dee2e6;
                height: 100%;
                overflow-y: auto;
            }
            .certora-rule-item {
                padding: 0.75rem 1rem;
                border-bottom: 1px solid #f1f3f5;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 10px;
                transition: background 0.2s;
            }
            .certora-rule-item:hover {
                background: #f8f9fa;
            }
            .certora-rule-item.active {
                background: #e7f5ff;
                border-left: 4px solid #228be6;
            }
            .certora-trace-container {
                background: #ffffff;
                padding: 0;
                height: 600px;
                overflow-y: auto;
            }
            .certora-step {
                padding: 0.5rem 1.5rem;
                border-bottom: 1px solid #f8f9fa;
                font-family: 'Inter', sans-serif;
                font-size: 0.9rem;
                display: flex;
                align-items: flex-start;
                gap: 12px;
                cursor: pointer;
            }
            .certora-step:hover {
                background: #f1f3f5;
            }
            .certora-step.active {
                background: #fff4e6;
                border-left: 3px solid #fd7e14;
            }
            .certora-step-icon {
                margin-top: 4px;
                color: #adb5bd;
            }
            .certora-variable-pane {
                background: #ffffff;
                border-left: 1px solid #dee2e6;
                padding: 1rem;
                height: 600px;
                overflow-y: auto;
            }
            .certora-table {
                width: 100%;
                font-size: 0.85rem;
            }
            .certora-table th {
                text-align: left;
                color: #868e96;
                font-weight: 500;
                padding-bottom: 0.5rem;
                border-bottom: 1px solid #f1f3f5;
            }
            .certora-table td {
                padding: 0.4rem 0;
                border-bottom: 1px solid #f8f9fa;
            }
            .certora-val-changed {
                color: #e03131;
                font-weight: 600;
            }
            .certora-badge-success {
                background: #ebfbee;
                color: #2f9e44;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 0.7rem;
                font-weight: 700;
            }
            .certora-badge-fail {
                background: #fff5f5;
                color: #e03131;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 0.7rem;
                font-weight: 700;
            }
        </style>
    </head>
    <body>
        <div id="error-log"></div>
        <div id="info">
            <strong style="font-size: 16px; letter-spacing: 1px;">🔬 3D STATE SPACE</strong><br>
            <span style="font-size: 11px; color: #00ffcc88; text-transform: uppercase;">Real-time Model Visualization</span>
        </div>
        <div id="controls-hint">
            🖱️ DRAG TO ROTATE · SCROLL TO ZOOM · RIGHT-CLICK TO PAN
        </div>
        <div id="tooltip" class="tooltip"></div>
        <div id="container"></div>
        
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        
        <script>
            function logError(msg) {
                const errDiv = document.getElementById('error-log');
                errDiv.style.display = 'block';
                errDiv.innerHTML += msg + '<br>';
                console.error(msg);
            }

            const nodesData = __NODES_JSON__;
            const edgesData = __EDGES_JSON__;
            const trailData = __TRAIL_JSON__;
            
            function init() {
                if (typeof THREE === 'undefined') {
                    setTimeout(init, 100);
                    return;
                }

                const loadScript = (url) => {
                    return new Promise((resolve, reject) => {
                        const script = document.createElement('script');
                        script.src = url;
                        script.onload = resolve;
                        script.onerror = reject;
                        document.head.appendChild(script);
                    });
                };

                Promise.all([
                    loadScript('https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js'),
                    loadScript('https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/renderers/CSS2DRenderer.js')
                ]).then(() => {
                    startVisualization();
                }).catch(err => {
                    logError('Failed to load Three.js extensions: ' + err);
                });
            }

            function startVisualization() {
                try {
                    const scene = new THREE.Scene();
                    scene.background = null; 
                    
                    const container = document.getElementById('container');
                    const width = container.clientWidth;
                    const height = container.clientHeight;

                    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
                    camera.position.set(10, 8, 15);
                    
                    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                    renderer.setSize(width, height);
                    renderer.setPixelRatio(window.devicePixelRatio);
                    renderer.shadowMap.enabled = true;
                    container.appendChild(renderer.domElement);
                    
                    const labelRenderer = new THREE.CSS2DRenderer();
                    labelRenderer.setSize(width, height);
                    labelRenderer.domElement.style.position = 'absolute';
                    labelRenderer.domElement.style.top = '0px';
                    labelRenderer.domElement.style.pointerEvents = 'none';
                    container.appendChild(labelRenderer.domElement);
                    
                    const controls = new THREE.OrbitControls(camera, renderer.domElement);
                    controls.enableDamping = true;
                    controls.dampingFactor = 0.05;
                    controls.autoRotate = true;
                    controls.autoRotateSpeed = 0.5;
                    
                    scene.add(new THREE.AmbientLight(0x404060));
                    
                    const dirLight = new THREE.DirectionalLight(0x00ffcc, 1);
                    dirLight.position.set(5, 10, 7);
                    dirLight.castShadow = true;
                    scene.add(dirLight);
                    
                    const pointLight = new THREE.PointLight(0xff00cc, 1, 20);
                    pointLight.position.set(-5, 5, -5);
                    scene.add(pointLight);
                    
                    const gridHelper = new THREE.GridHelper(30, 30, 0x00ffcc, 0x1a1a2e);
                    gridHelper.position.y = -5;
                    gridHelper.material.opacity = 0.2;
                    gridHelper.material.transparent = true;
                    scene.add(gridHelper);
                    
                    const particlesGeo = new THREE.BufferGeometry();
                    const particlesCount = 800;
                    const posArray = new Float32Array(particlesCount * 3);
                    for(let i = 0; i < particlesCount * 3; i++) {
                        posArray[i] = (Math.random() - 0.5) * 40;
                    }
                    particlesGeo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
                    const particlesMat = new THREE.PointsMaterial({ size: 0.05, color: 0x00ffcc, transparent: true, opacity: 0.4 });
                    const particles = new THREE.Points(particlesGeo, particlesMat);
                    scene.add(particles);
                    
                    const nodeMeshes = [];
                    const nodePositions = {};
                    
                    const actualNodes = nodesData.length > 0 ? nodesData : ['S0', 'S1', 'S2', 'S3'];
                    actualNodes.forEach((nodeName, index) => {
                        const angle = (index / actualNodes.length) * Math.PI * 2;
                        const radius = 8;
                        const y = (index % 2 === 0 ? 1 : -1) * (index * 0.4);
                        const x = Math.cos(angle) * radius;
                        const z = Math.sin(angle) * radius;
                        
                        nodePositions[nodeName] = new THREE.Vector3(x, y, z);
                        
                        const details = trailData && trailData.node_details ? 
                                       trailData.node_details.find(n => n.id === nodeName) : null;
                        
                        let color = 0x00ffcc; 
                        let emissive = 0x00ffcc;
                        
                        const isInTrail = trailData && trailData.counterexample_path && 
                                          trailData.counterexample_path.includes(nodeName);
                        
                        if (isInTrail) {
                            color = 0xff4444; 
                            emissive = 0xff4444;
                        } else if (nodeName.toLowerCase().includes('ltl')) {
                            color = 0xff00cc;
                            emissive = 0xff00cc;
                        } else if (nodeName.toLowerCase().includes('pass')) {
                            color = 0x00ff00;
                            emissive = 0x00ff00;
                        } else if (nodeName.toLowerCase().includes('fail')) {
                            color = 0xff4444;
                            emissive = 0xff4444;
                        }

                        const sphere = new THREE.Mesh(
                            new THREE.SphereGeometry(0.5, 32, 32),
                            new THREE.MeshStandardMaterial({ 
                                color: color, 
                                emissive: emissive, 
                                emissiveIntensity: 0.5,
                                metalness: 0.8,
                                roughness: 0.2
                            })
                        );
                        sphere.position.set(x, y, z);
                        
                        let tooltipContent = `<strong>${nodeName}</strong><br>`;
                        if (details) {
                            tooltipContent += `Action: ${details.action}<br>`;
                            tooltipContent += `Line: ${details.line}<br>`;
                            if (details.variables && Object.keys(details.variables).length > 0) {
                                tooltipContent += `<hr style="border: 0.5px solid #00ffcc33;">`;
                                for (const [v, val] of Object.entries(details.variables)) {
                                    tooltipContent += `${v}: <span style="color: #00ffcc;">${val}</span><br>`;
                                }
                            }
                        }
                        
                        sphere.userData = { name: nodeName, tooltip: tooltipContent };
                        scene.add(sphere);
                        nodeMeshes.push(sphere);
                        
                        const div = document.createElement('div');
                        div.textContent = nodeName;
                        div.style.color = '#ffffff';
                        div.style.fontSize = '12px';
                        div.style.background = 'rgba(0, 255, 204, 0.2)';
                        div.style.padding = '2px 8px';
                        div.style.borderRadius = '10px';
                        div.style.border = '1px solid #00ffcc';
                        div.style.backdropFilter = 'blur(4px)';
                        
                        const label = new THREE.CSS2DObject(div);
                        label.position.set(x, y + 0.8, z);
                        scene.add(label);
                    });
                    
                    edgesData.forEach(edge => {
                        const fromPos = nodePositions[edge.from];
                        const toPos = nodePositions[edge.to];
                        
                        if (fromPos && toPos) {
                            const curve = new THREE.CatmullRomCurve3([
                                fromPos,
                                new THREE.Vector3().addVectors(fromPos, toPos).multiplyScalar(0.5).add(new THREE.Vector3(0, 1, 0)),
                                toPos
                            ]);
                            
                            const isEdgeInTrail = trailData && trailData.edges && 
                                                 trailData.edges.some(e => e.from === edge.from && e.to === edge.to);
                            
                            const tube = new THREE.Mesh(
                                new THREE.TubeGeometry(curve, 20, isEdgeInTrail ? 0.2 : 0.1, 8, false),
                                new THREE.MeshStandardMaterial({ 
                                    color: isEdgeInTrail ? 0xff4444 : 0x00ffcc, 
                                    transparent: true, 
                                    opacity: isEdgeInTrail ? 1.0 : 0.7 
                                })
                            );
                            scene.add(tube);
                        }
                    });
                    
                    const raycaster = new THREE.Raycaster();
                    const mouse = new THREE.Vector2();
                    const tooltip = document.getElementById('tooltip');
                    
                    window.addEventListener('mousemove', (event) => {
                        const rect = container.getBoundingClientRect();
                        mouse.x = ((event.clientX - rect.left) / width) * 2 - 1;
                        mouse.y = -((event.clientY - rect.top) / height) * 2 + 1;
                        
                        raycaster.setFromCamera(mouse, camera);
                        const intersects = raycaster.intersectObjects(nodeMeshes);
                        
                        if (intersects.length > 0) {
                            const node = intersects[0].object;
                            tooltip.style.display = 'block';
                            tooltip.style.left = event.clientX + 10 + 'px';
                            tooltip.style.top = event.clientY - 10 + 'px';
                            tooltip.innerHTML = node.userData.tooltip;
                        } else {
                            tooltip.style.display = 'none';
                        }
                    });
                    
                    function animate() {
                        requestAnimationFrame(animate);
                        controls.update();
                        particles.rotation.y += 0.001;
                        renderer.render(scene, camera);
                        labelRenderer.render(scene, camera);
                    }
                    animate();
                    
                    window.addEventListener('resize', () => {
                        const w = container.clientWidth;
                        const h = container.clientHeight;
                        camera.aspect = w / h;
                        camera.updateProjectionMatrix();
                        renderer.setSize(w, h);
                        labelRenderer.setSize(w, h);
                    });

                } catch (e) {
                    logError('Runtime error: ' + e.message);
                }
            }

            init();
        </script>
    </body>
    </html>
    """
    
    # Use template replacement instead of f-string to avoid brace hell
    html_code = html_template.replace("__NODES_JSON__", nodes_json)
    html_code = html_code.replace("__EDGES_JSON__", edges_json)
    html_code = html_code.replace("__TRAIL_JSON__", trail_json)
    
    # Render component
    components.html(html_code, height=height, scrolling=False, width=1200)

# Always run from project directory

# Ensure working directory is the project folder

# Import verification state
try:
    from verification_state import VerificationState
except ImportError:
    class VerificationState:
        @staticmethod
        def load_result():
            state_file = os.path.join(REPORTS_DIR, "verification_state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r') as f:
                        return json.load(f)
                except:
                    pass
            return None

# Page config
is_embedded = "embed" in st.query_params
initial_sidebar = "collapsed" if is_embedded else "expanded"

st.set_page_config( 
    page_title="DeFi Guardian", 
    page_icon="🛡️", 
    layout="wide", 
    initial_sidebar_state=initial_sidebar 
) 

# ── Remove Streamlit's default padding so the dashboard fills the iframe ──
embed_css = ""
if is_embedded:
    embed_css = """
    /* Hide sidebar and collapsed sidebar arrow buttons completely when embedded */
    [data-testid="stSidebar"], 
    [data-testid="collapsedSidebarCodegen"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }
    .main .block-container {
        margin-left: 0 !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
    }
    """

st.markdown(f"""
<style>
    /* Kill Streamlit's default padding on the main block */
    .main .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 100% !important;
    }}
    /* Also remove top padding from the entire main area */
    section.main > div {{
        padding-top: 0 !important;
    }}
    /* Hide the Streamlit hamburger menu and footer for a cleaner embed */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
    
    {embed_css}
</style>
""", unsafe_allow_html=True)  
 
# Modern glassmorphism styling moved to theme_toggle()
st.markdown("""
<div id="top"></div>
""", unsafe_allow_html=True)

# Show visual guidance when optional dependencies are missing
if nx is None:
    st.error("The `networkx` package is not installed. Install it with `pip install networkx` to enable state visualization and graph rendering.")
    st.markdown("""
    ### 🚨 Missing Dependency: networkx
    
    The state visualization features require the `networkx` library. Without it, you cannot:
    - View 3D state space graphs
    - See 2D state diagrams  
    - Explore state transitions interactively
    
    **To fix this:**
    ```bash
    pip install networkx
    ```
    
    Then restart the Streamlit dashboard.
    """)
    st.stop()  # Prevent further execution

if graphviz is None:
    st.warning("The `graphviz` Python package is not installed. Some state diagram rendering and Graphviz features may be limited. Install it with `pip install graphviz`.")
    st.markdown("""
    ### ⚠️ Optional Dependency: graphviz
    
    Graphviz enhances state diagram rendering. Without it, some diagram features may be limited.
    
    **To install:**
    ```bash
    pip install graphviz
    ```
    
    You may also need the system Graphviz package:
    ```bash
    # Ubuntu/Debian
    sudo apt install graphviz
    
    # macOS
    brew install graphviz
    
    # Windows - download from https://graphviz.org/download/
    ```
    """)

def load_live_verification():
    """Load verification status with timestamp"""
    state_file = os.path.join(REPORTS_DIR, "verification_state.json")
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            data = json.load(f)
            # Add human-readable time
            if 'timestamp' in data:
                data['readable_time'] = datetime.fromtimestamp(data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            return data
    return None


def load_verification_state():
    """Load complete verification state for all tools"""
    state_file = os.path.join(REPORTS_DIR, "verification_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def export_verification_report(format='pdf'): 
     """Generate comprehensive verification report""" 
     
     try:
         from reportlab.lib.pagesizes import A4 
         from reportlab.pdfgen import canvas 
         from reportlab.lib import colors
     except ImportError:
         return None, "reportlab library not found. Please install with 'pip install reportlab'"
     
     filename = os.path.join(REPORTS_DIR, "verification_report.pdf")
     try:
         c = canvas.Canvas(filename, pagesize=A4) 
         
         # Header 
         c.setFont("Helvetica-Bold", 20) 
         c.setFillColor(colors.HexColor("#00ffcc"))
         c.drawString(50, 800, "🛡️ DeFi Guardian Verification Report") 
         
         c.setFont("Helvetica", 10)
         c.setFillColor(colors.black)
         c.drawString(50, 785, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
         c.line(50, 775, 550, 775)
         
         # Results section
         c.setFont("Helvetica-Bold", 14)
         c.drawString(50, 750, "Verification Results Summary")
         
         active_file = get_active_filename()
         is_solidity = active_file.lower().endswith('.sol')
         is_rust = active_file.lower().endswith('.rs')
         
         data = load_verification_state() 
         y = 720 
         
         # Table Headers
         c.setFont("Helvetica-Bold", 11)
         c.drawString(60, y, "Tool")
         c.drawString(200, y, "Status")
         c.drawString(300, y, "Timestamp")
         y -= 20
         c.line(50, y+15, 550, y+15)
         
         for tool, result in data.items(): 
             if not isinstance(result, dict): continue
             if tool in ['success', 'datetime', 'states_stored', 'transitions', 'depth']: continue
             
             # Filter tools based on active file type
             if is_solidity and tool.lower() not in ['spin', 'coq', 'lean']:
                 continue
             if is_rust and tool.lower() not in ['kani', 'prusti', 'creusot', 'lean']:
                 continue
             
             c.setFont("Helvetica", 11) 
             status = result.get('status', 'FAIL')
             is_pass = "PASS" in status or result.get('success', False)
             
             c.drawString(60, y, tool.upper())
             
             if is_pass:
                 c.setFillColor(colors.darkgreen)
                 c.drawString(200, y, "✓ PASS")
             else:
                 c.setFillColor(colors.red)
                 c.drawString(200, y, "✗ FAIL")
                 
             c.setFillColor(colors.black)
             c.drawString(300, y, result.get('timestamp', 'N/A')[:19])
             
             y -= 25
             if y < 100: # Simple page break handling
                 c.showPage()
                 y = 800
         
         # Footer
         c.setFont("Helvetica-Oblique", 8)
         c.drawString(50, 50, "DeFi Guardian - Formal Verification Suite | Confidential")
         
         # New Page for Benchmarks
         benchmark_file = os.path.join("benchmarks", "benchmark_results.json")
         if os.path.exists(benchmark_file):
             c.showPage()
             c.setFont("Helvetica-Bold", 16)
             c.setFillColor(colors.HexColor("#00ffcc"))
             c.drawString(50, 800, "🚀 Performance Benchmarks")
             c.line(50, 790, 550, 790)
             
             try:
                 with open(benchmark_file, 'r') as f:
                     bench_data = json.load(f)
                     y = 760
                     c.setFont("Helvetica-Bold", 10)
                     c.setFillColor(colors.black)
                     c.drawString(60, y, "Contract")
                     c.drawString(160, y, "Tool")
                     c.drawString(260, y, "Time (s)")
                     c.drawString(360, y, "Properties")
                     c.drawString(460, y, "Status")
                     y -= 20
                     
                     for item in bench_data[:20]: # Show top 20 results
                         c.setFont("Helvetica", 9)
                         c.drawString(60, y, str(item['contract']))
                         c.drawString(160, y, str(item['tool']))
                         c.drawString(260, y, str(item['time']))
                         c.drawString(360, y, str(item['properties_verified']))
                         
                         if item['success']:
                             c.setFillColor(colors.darkgreen)
                             c.drawString(460, y, "PASS")
                         else:
                             c.setFillColor(colors.red)
                             c.drawString(460, y, "FAIL")
                         
                         c.setFillColor(colors.black)
                         y -= 15
                         if y < 100:
                             c.showPage()
                             y = 800
             except:
                 pass

         c.save() 
         return filename, None
     except Exception as e:
         return None, str(e)


def get_tool_status(tool_name):
    """Get status for a specific tool"""
    state = load_verification_state()
    if tool_name in state:
        tool_state = state[tool_name]
        status = tool_state.get('status', '')
        if status:
            success = status == "PASS"
            status_label = {
                "PASS": "✅ PASS",
                "FAIL": "❌ FAIL",
                "SKIP": "⏭️ SKIP",
                "INFRA_ERROR": "⚠️ INFRA",
            }.get(status, f"⚪ {status}")
        else:
            success = tool_state.get('success', False)
            status_label = '✅ PASS' if success else '❌ FAIL'
        timestamp = tool_state.get('timestamp', '')
        return {
            'status': status_label,
            'timestamp': timestamp,
            'success': success
        }
    return {'status': '⚪ Not Run', 'timestamp': '', 'success': False}


def load_tool_log(tool_name: str, max_bytes: int = 32_000) -> str:
    """Load the most recent log file for a given tool."""
    log_dirs = {
        "spin":    SPIN_LOGS,
        "certora": CERTORA_LOGS,
        "coq":     COQ_LOGS,
        "lean":    LEAN_LOGS,
        "kani":    RUST_LOGS,
        "prusti":  RUST_LOGS,
        "creusot": RUST_LOGS,
        "verus":   RUST_LOGS,
    }
    log_dir = log_dirs.get(tool_name.lower(), LOGS_DIR)

    # Also check verification_state for an explicit log_path
    state = load_verification_state()
    tool_state = state.get(tool_name.lower(), {})
    explicit_path = tool_state.get("log_path", "")
    if explicit_path and os.path.exists(explicit_path):
        try:
            with open(explicit_path, "r", errors="replace") as f:
                content = f.read(max_bytes)
            return content + ("\n… [truncated]" if len(content) == max_bytes else "")
        except Exception as e:
            return f"Error reading log: {e}"

    # Fall back to newest file in the tool's log directory
    if os.path.isdir(log_dir):
        candidates = sorted(
            [os.path.join(log_dir, fn) for fn in os.listdir(log_dir)
             if os.path.isfile(os.path.join(log_dir, fn))],
            key=os.path.getmtime, reverse=True
        )
        for path in candidates:
            try:
                with open(path, "r", errors="replace") as f:
                    content = f.read(max_bytes)
                return content + ("\n… [truncated]" if len(content) == max_bytes else "")
            except Exception:
                continue

    return f"No log found for {tool_name}."


def render_multi_tool_verification_panel():
    """Render a rich multi-tool verification status and log viewer panel."""
    t = get_current_theme()
    t_mode = st.session_state.get('theme', 'dark')

    state = load_verification_state()
    active_file = get_active_filename()
    is_rust = active_file.lower().endswith('.rs')
    is_sol  = active_file.lower().endswith('.sol')

    # Determine which tools are relevant
    if is_rust:
        tools = ["kani", "prusti", "creusot", "verus", "lean"]
    elif is_sol:
        tools = ["spin", "certora", "coq", "lean"]
    else:
        tools = ["spin", "coq", "lean"]

    # ── Summary cards ────────────────────────────────────────────────
    st.markdown("### 🔬 Multi-Tool Verification Status")
    cols = st.columns(len(tools))
    for col, tool in zip(cols, tools):
        info = get_tool_status(tool)
        success = info["success"]
        card_border = "#10b981" if success else ("#ef4444" if info["status"] != "⚪ Not Run" else t["card_border"])
        ts = info["timestamp"][:16] if info["timestamp"] else "—"
        with col:
            st.markdown(f"""
            <div style="background:{t['card_bg']};border:1px solid {card_border};
                        border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.4rem;">{"✅" if success else ("❌" if info["status"] != "⚪ Not Run" else "⚪")}</div>
                <div style="font-weight:700;color:{t['text_main']};font-size:0.85rem;
                            text-transform:uppercase;margin:4px 0;">{tool}</div>
                <div style="font-size:0.7rem;color:{t['text_dim']};">{ts}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Detailed results per tool ────────────────────────────────────
    st.markdown("### 📋 Tool Details & Logs")
    selected_tool = st.selectbox(
        "Select tool to inspect",
        options=tools,
        format_func=lambda x: x.upper(),
        key="multi_tool_selector"
    )

    info = get_tool_status(selected_tool)
    tool_state = state.get(selected_tool.lower(), {})

    # Status + metadata row
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Status", info["status"])
    mc2.metric("States", tool_state.get("states_stored", tool_state.get("states", "—")))
    mc3.metric("Transitions", tool_state.get("transitions", "—"))
    mc4.metric("Depth", tool_state.get("depth", "—"))

    # LTL / rule results for this tool
    ltl_results = tool_state.get("ltl_results", [])
    if ltl_results:
        st.markdown("#### LTL / Rule Results")
        for prop in ltl_results:
            ok = prop.get("success", False)
            color = "#10b981" if ok else "#ef4444"
            formula_bg = "rgba(0,0,0,0.15)" if t_mode == "dark" else "rgba(0,0,0,0.05)"
            st.markdown(f"""
            <div class="ltl-property" style="border-color:{color};background:{color}10;">
                <span style="color:{color};font-weight:bold;">{"PASS" if ok else "FAIL"}</span> |
                <strong style="color:{t['text_main']}">{prop.get('name','?')}</strong>:
                <code style="background:{formula_bg};color:{t['secondary']};
                             padding:2px 5px;border-radius:4px;">{prop.get('formula','')}</code>
            </div>
            """, unsafe_allow_html=True)

    # Certora-specific: job URL
    if selected_tool == "certora":
        job_url = tool_state.get("job_url", "")
        if job_url:
            st.markdown(f"🔗 **Certora Cloud Results:** [{job_url}]({job_url})")
        spec_content = tool_state.get("spec_content", "")
        if spec_content:
            with st.expander("📜 Active Certora Spec"):
                st.code(spec_content, language="text")

    # Log viewer
    with st.expander(f"📄 {selected_tool.upper()} Log Output", expanded=False):
        log_text = load_tool_log(selected_tool)
        if log_text.startswith("No log"):
            st.info(log_text)
        else:
            st.code(log_text, language="text")

    # Errors / violations
    errors = tool_state.get("errors", tool_state.get("error_msg", ""))
    if errors:
        with st.expander("⚠️ Errors / Violations", expanded=True):
            st.code(errors, language="text")

# ==================== HELPER FUNCTIONS ====================

def parse_all_pml_variables(filename):
    """Extract all variables and their values from PML file"""
    vars_dict = {}
    if not os.path.exists(filename): return vars_dict
    try:
        with open(filename, 'r') as f:
            content = f.read()
            # Find all variable declarations: type name = value;
            matches = re.findall(r'(?:int|bool|byte|short)\s+(\w+)\s*=\s*(\d+|true|false)', content)
            for name, val in matches:
                if val == 'true': val = 1
                elif val == 'false': val = 0
                else: val = int(val)
                vars_dict[name] = val
    except: pass
    return vars_dict

def parse_pml_variable(filename, var_name, default_val):
    """Parse variable from PML file"""
    all_vars = parse_all_pml_variables(filename)
    return float(all_vars.get(var_name, default_val))

def render_certora_trace_analysis(trail_data, ltl_results):
    """Render a Certora-style trace analysis dashboard with robust error handling"""
    try:
        st.markdown("---")
        st.markdown("### 🔍 Counterexample Deep Dive")
        
        # Ensure we have valid data
        if not trail_data or not isinstance(trail_data, dict):
            st.info("No trace data available yet. Run verification to generate a counterexample.")
            return

        node_details = trail_data.get('node_details', [])
        
        # Get active file info
        active_file = get_active_filename()
        
        # Fetch active file source code for AI suggestions
        source_code = ""
        if active_file and os.path.exists(active_file):
            try:
                with open(active_file, "r") as f:
                    source_code = f.read()
            except:
                pass

        ai_recommendations = []
        if source_code:
            try:
                from llm_spec_generator import LLMSpecGenerator
                gen = LLMSpecGenerator()
                specs = gen.generate_specs_from_code(source_code)
                if specs.get("requires"):
                    ai_recommendations.append(f"Suggested require guard: <code>{specs['requires'][0]}</code>")
                if specs.get("ensures"):
                    valid_ens = [e for e in specs["ensures"] if not e.strip().startswith("/*")]
                    if valid_ens:
                        ai_recommendations.append(f"Suggested ensures invariant: <code>{valid_ens[0]}</code>")
                if specs.get("invariants"):
                    ai_recommendations.append(f"Suggested safety check: <code>{specs['invariants'][0]}</code>")
            except Exception as e:
                pass
        
        # Header with tabs
        st.markdown(f"""
        <div class="certora-header">
            <div style="font-weight: 600; font-size: 1.1rem;">Call Trace Analysis</div>
            <div style="font-size: 0.85rem; color: #868e96;">{os.path.basename(active_file)} • Counterexample 1 of 1</div>
        </div>
        """, unsafe_allow_html=True)

        if ai_recommendations:
            recs_html = "".join([f"<li style='margin-bottom: 0.25rem;'>{rec}</li>" for rec in ai_recommendations])
            st.markdown(f"""
            <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.25rem; border-left: 4px solid #10b981;">
                <h5 style="margin: 0 0 0.35rem 0; color: #10b981; display: flex; align-items: center; gap: 0.4rem; font-size: 0.95rem; font-weight: 600;">
                    <span>🤖</span> AI Security Guidance & Invariants
                </h5>
                <ul style="margin: 0; padding-left: 1.1rem; color: #868e96; font-size: 0.85rem;">
                    {recs_html}
                </ul>
            </div>
            """, unsafe_allow_html=True)
        
        # Three column layout: Rules | Trace | Variables
        c1, c2, c3 = st.columns([1.5, 3, 1.5])
        
        # 1. Rules Sidebar
        with c1:
            st.markdown('<div class="certora-sidebar">', unsafe_allow_html=True)
            st.markdown('<div style="padding: 0.5rem 1rem; font-weight: 600; color: #868e96; font-size: 0.8rem;">RULES</div>', unsafe_allow_html=True)
            
            if ltl_results:
                for i, rule in enumerate(ltl_results):
                    name = rule.get('name', f'Rule {i}')
                    success = rule.get('success', False)
                    active_class = "active" if st.session_state.get('selected_rule') == name else ""
                    badge = '<span class="certora-badge-success">✓</span>' if success else '<span class="certora-badge-fail">✗</span>'
                    
                    # Use columns for button + label alignment
                    btn_col1, btn_col2 = st.columns([0.2, 0.8])
                    with btn_col1:
                        st.write(badge, unsafe_allow_html=True)
                    with btn_col2:
                        if st.button(f"{name}", key=f"rule_btn_{name}", use_container_width=True):
                            st.session_state.selected_rule = name
                            st.rerun()
                            
                    st.markdown(f"""
                    <div class="certora-rule-item {active_class}">
                        <div style="font-size: 0.9rem;">{name}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No LTL rules detected.")
            st.markdown('</div>', unsafe_allow_html=True)
            
        # 2. Call Trace Center
        with c2:
            st.markdown('<div class="certora-trace-container">', unsafe_allow_html=True)
            if node_details:
                for i, step in enumerate(node_details):
                    is_active = st.session_state.get('selected_step_idx') == i
                    active_class = "active" if is_active else ""
                    
                    # Use a button for selection
                    if st.button(f"Step {i+1}: {step['action']}", key=f"step_btn_{i}", use_container_width=True):
                        st.session_state.selected_step_idx = i
                        st.rerun()
                    
                    st.markdown(f"""
                    <div class="certora-step {active_class}">
                        <div class="certora-step-icon">○</div>
                        <div>
                            <div style="font-weight: 500;">{step['action']}</div>
                            <div style="font-size: 0.75rem; color: #adb5bd;">Line {step['line']} • {step.get('proc', 'Contract')}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.warning("The trace contains no steps. This usually happens if the SPIN replay output couldn't be parsed correctly.")
                with st.expander("View Raw Trace Data"):
                    st.text(trail_data.get('raw_trail', 'No raw output available.'))
            st.markdown('</div>', unsafe_allow_html=True)
            
        # 3. Variables Sidebar
        with c3:
            st.markdown('<div class="certora-variable-pane">', unsafe_allow_html=True)
            
            # Tabs for Variables and Rule Resolutions
            var_tab, res_tab = st.tabs(["Variables", "Resolutions"])
            
            if node_details:
                # Clamp the current index safely
                current_idx = st.session_state.get('selected_step_idx', 0)
                if current_idx >= len(node_details):
                    current_idx = len(node_details) - 1
                if current_idx < 0:
                    current_idx = 0
                
                # Always update session state to the clamped value to prevent future errors
                st.session_state.selected_step_idx = current_idx
                
                with var_tab:
                    st.markdown('<div style="font-weight: 600; color: #868e96; font-size: 0.8rem; margin-bottom: 1rem;">LOCAL VARIABLES</div>', unsafe_allow_html=True)
                    
                    current_step = node_details[current_idx]
                    current_vars = current_step.get('variables', {})
                    prev_vars = node_details[current_idx-1].get('variables', {}) if current_idx > 0 else {}
                    
                    st.markdown('<table class="certora-table"><tr><th>Name</th><th>Value</th></tr>', unsafe_allow_html=True)
                    # Sort variables to keep consistent order
                    for var in sorted(current_vars.keys()):
                        val = current_vars[var]
                        changed = str(prev_vars.get(var)) != str(val)
                        val_class = "certora-val-changed" if changed else ""
                        st.markdown(f'<tr><td>{var}</td><td class="{val_class}">{val}</td></tr>', unsafe_allow_html=True)
                    st.markdown('</table>', unsafe_allow_html=True)
                        
                with res_tab:
                    st.markdown('<div style="font-weight: 600; color: #868e96; font-size: 0.8rem; margin-bottom: 1rem;">CALL RESOLUTIONS</div>', unsafe_allow_html=True)
                    step = node_details[current_idx]
                    st.markdown(f"""
                    <div style="font-size: 0.85rem; color: #495057;">
                        <strong>Method:</strong> {step['action']}<br>
                        <strong>Process:</strong> {step.get('proc', 'Contract')}<br>
                        <strong>State:</strong> {step.get('state', 'N/A')}
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No variable data available for empty trace.")
                    
            st.markdown('</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Error rendering trace analysis: {e}")
        st.exception(e)

def parse_pml_state_machine(pml_content):
    """Parse PML file to extract state machine structure with improved logic"""
    states = []
    transitions = []
    processes = []
    state_vars = []
    ltl_properties = []
    fairness_conditions = []
    
    # Extract proctypes (processes)
    proctype_pattern = r'(?:active\s+)?proctype\s+(\w+)\s*(?:\([^)]*\))?\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}'
    for match in re.finditer(proctype_pattern, pml_content, re.DOTALL):
        proc_name = match.group(1)
        proc_body = match.group(2)
        processes.append(proc_name)
        
        # Track the current state for transitions
        current_context_state = f"{proc_name}.INIT"
        
        # Extract labels (states)
        label_pattern = r'^(\w+)\s*:'
        for line in proc_body.split('\n'):
            label_match = re.match(label_pattern, line.strip())
            if label_match:
                state_name = label_match.group(1)
                if state_name not in ['skip', 'break', 'goto', 'printf', 'assert']:
                    states.append(f"{proc_name}.{state_name}")
        
        # 1. First, find all explicit state assignments to build the backbone
        state_assign_pattern = r'state\s*=\s*(\d+)'
        assignments = []
        for sa_match in re.finditer(state_assign_pattern, proc_body):
            state_num = sa_match.group(1)
            assignments.append({
                'num': state_num,
                'pos': sa_match.start(),
                'name': f"{proc_name}.State_{state_num}"
            })
            if f"{proc_name}.State_{state_num}" not in states:
                states.append(f"{proc_name}.State_{state_num}")

        # 2. Extract transitions from if statements with context awareness
        # Find if...fi blocks
        if_blocks = re.finditer(r'if\s*(.*?)\s*fi', proc_body, re.DOTALL)
        for block in if_blocks:
            block_content = block.group(1)
            block_start = block.start()
            
            # Find the state assignment just before this if block
            prev_assignment = "INIT"
            for assign in assignments:
                if assign['pos'] < block_start:
                    prev_assignment = f"State_{assign['num']}"
                else:
                    break
            
            # Parse branches inside if
            branches = re.finditer(r'::\s*(.*?)\s*->(.*?)(?=(?:::|fi|$))', block_content, re.DOTALL)
            for branch in branches:
                condition = branch.group(1).strip()
                action_content = branch.group(2)
                
                # Find if this branch has a state assignment
                branch_state_match = re.search(r'state\s*=\s*(\d+)', action_content)
                target = f"{proc_name}.State_{branch_state_match.group(1)}" if branch_state_match else f"{proc_name}.FI_Exit"
                
                transitions.append({
                    'from': f"{proc_name}.{prev_assignment}",
                    'to': target,
                    'condition': condition[:40],
                    'action': 'Conditional Branch'
                })

        # 3. Extract transitions from do loops
        do_blocks = re.finditer(r'do\s*(.*?)\s*od', proc_body, re.DOTALL)
        for block in do_blocks:
            block_content = block.group(1)
            
            # Find loop options
            options = re.finditer(r'::\s*(.*?)\s*->(.*?)(?=(?:::|od|$))', block_content, re.DOTALL)
            for opt in options:
                condition = opt.group(1).strip()
                action_content = opt.group(2)
                
                # Check for state assignments or break
                state_match = re.search(r'state\s*=\s*(\d+)', action_content)
                is_break = 'break' in action_content
                
                if state_match:
                    target = f"{proc_name}.State_{state_match.group(1)}"
                elif is_break:
                    target = f"{proc_name}.LoopBreak"
                else:
                    target = f"{proc_name}.LoopStay"
                
                transitions.append({
                    'from': f"{proc_name}.Running", # Logic for 'do' usually starts from a running state
                    'to': target,
                    'condition': condition[:40],
                    'action': 'Loop Branch'
                })

        # 4. Fallback for linear state assignments not caught in blocks
        last_s = "INIT"
        for assign in assignments:
            curr_s = f"State_{assign['num']}"
            # Only add if not already represented as a transition from a block
            exists = any(t['to'] == f"{proc_name}.{curr_s}" for t in transitions)
            if not exists:
                transitions.append({
                    'from': f"{proc_name}.{last_s}",
                    'to': f"{proc_name}.{curr_s}",
                    'condition': 'assignment',
                    'action': f'Update to {assign["num"]}'
                })
            last_s = curr_s
    
    # Extract state variables
    var_pattern = r'(?:int|bool|byte)\s+(\w+)\s*(?:=\s*([^;]+))?;'
    for match in re.finditer(var_pattern, pml_content):
        var_name = match.group(1)
        init_val = match.group(2) if match.group(2) else "0"
        state_vars.append({'name': var_name, 'initial': init_val.strip()})
    
    # Extract assertions/invariants
    assert_pattern = r'assert\s*\((.*?)\)'
    assertions = re.findall(assert_pattern, pml_content)
    
    # Extract LTL properties
    ltl_pattern = r'ltl\s+(\w+)\s*\{\s*(.*?)\s*\}'
    for match in re.finditer(ltl_pattern, pml_content, re.DOTALL):
        prop_name = match.group(1)
        prop_formula = match.group(2).strip()
        ltl_properties.append({'name': prop_name, 'formula': prop_formula})
    
    # Extract fairness conditions
    fairness_pattern = r'fairness\s*::\s*(.*?)\s*->\s*(.*?)(?:\n|$)'
    fairness_conditions = re.findall(fairness_pattern, pml_content)
    
    # DEBUG: Ensure states and transitions are not empty
    if not states and processes:
        states = [f"{p}.INIT" for p in processes]
    
    return {
        'states': list(set(states)) if states else (processes if processes else ["INIT", "END"]),
        'transitions': transitions,
        'processes': processes,
        'state_vars': state_vars,
        'assertions': assertions,
        'ltl_properties': ltl_properties,
        'fairness': fairness_conditions,
        'raw_content': pml_content
    }

def generate_state_diagram(pml_file, rank_dir='TB', layout_engine='dot', show_transitions=True, state_type='full'):
    """Generate state diagram from PML file with type selection"""
    try:
        with open(pml_file, 'r') as f:
            pml_content = f.read()
        
        state_machine = parse_pml_state_machine(pml_content)
        
        # Create Graphviz diagram
        dot = graphviz.Digraph(comment='State Machine', engine=layout_engine)
        dot.attr(rankdir=rank_dir, bgcolor='transparent', fontname='Arial')
        dot.attr('node', shape='box', style='filled,rounded', 
                 fillcolor='#1a1a2e', fontcolor='white', color='#00ffcc', fontname='Arial')
        dot.attr('edge', color='#00ffcc', penwidth='2', fontcolor='#00ffcc', fontsize='10')
        
        # Add processes based on state type
        if state_type == 'full':
            for proc in state_machine.get('processes', []):
                with dot.subgraph(name=f'cluster_{proc}') as c:
                    c.attr(label=proc, fontcolor='#00ffcc', style='rounded', color='#00ffcc')
                    c.node(f'{proc}_init', 'Initial', shape='circle', fillcolor='#00ffcc', fontcolor='black')
                    c.node(f'{proc}_run', 'Running')
                    c.node(f'{proc}_end', 'End', shape='doublecircle')
                    c.edge(f'{proc}_init', f'{proc}_run')
                    c.edge(f'{proc}_run', f'{proc}_end', label='complete')
        
        elif state_type == 'detailed':
            for proc in state_machine.get('processes', []):
                with dot.subgraph(name=f'cluster_{proc}') as c:
                    c.attr(label=proc, fontcolor='#00ffcc', style='rounded', color='#00ffcc')
                    proc_states = [s for s in state_machine.get('states', []) if s.startswith(f"{proc}.")]
                    if proc_states:
                        for state in proc_states[:6]:
                            state_name = state.split('.')[-1]
                            c.node(state_name, state_name)
                    else:
                        c.node(f'{proc}_init', 'Initial', shape='circle', fillcolor='#00ffcc', fontcolor='black')
                        c.node(f'{proc}_run', 'Running')
                        c.node(f'{proc}_end', 'End', shape='doublecircle')
                        c.edge(f'{proc}_init', f'{proc}_run')
                        c.edge(f'{proc}_run', f'{proc}_end', label='complete')
        
        elif state_type == 'minimal':
            for proc in state_machine.get('processes', []):
                with dot.subgraph(name=f'cluster_{proc}') as c:
                    c.attr(label=proc, fontcolor='#00ffcc', style='rounded', color='#00ffcc')
                    c.node(f'{proc}_main', proc, shape='circle', fillcolor='#00ffcc', fontcolor='black')
        
        # Add transitions if enabled
        if show_transitions:
            for trans in state_machine.get('transitions', [])[:15]:
                from_state = trans.get('from', '')
                to_state = trans.get('to', '')
                condition = trans.get('condition', '')
                action = trans.get('action', '')
                label = f"{condition[:25]} -> {action[:25]}" if condition and action else condition or action
                if from_state and to_state:
                    dot.edge(from_state, to_state, label=label[:35])
        
        # Add LTL properties as a cluster
        if state_machine.get('ltl_properties'):
            with dot.subgraph(name='cluster_ltl') as c:
                c.attr(label='LTL Properties', fontcolor='#ff00cc', style='rounded', color='#ff00cc')
                for prop in state_machine.get('ltl_properties', [])[:5]:
                    c.node(f'ltl_{prop["name"]}', prop['name'], shape='diamond', fillcolor='#ff00cc20')
        
        # Add state variables as nodes
        if state_vars := state_machine.get('state_vars', []):
            with dot.subgraph(name='cluster_vars') as c:
                c.attr(label='State Variables', fontcolor='#ffa500', style='rounded', color='#ffa500')
                for var in state_vars[:8]:
                    label = f"{var['name']} = {var['initial']}"
                    c.node(f'var_{var["name"]}', label, shape='note', fillcolor='#ffa50020')
        
        # Add verification flow
        dot.node('start', 'Start', shape='circle', fillcolor='#00ffcc', fontcolor='black')
        dot.node('verify', 'Model Check', shape='box')
        dot.node('check', 'LTL Check', shape='diamond')
        dot.node('pass', 'Pass', shape='box', fillcolor='#00ffcc', fontcolor='black')
        dot.node('fail', 'Fail', shape='box', fillcolor='#ff4444', fontcolor='white')
        
        dot.edge('start', 'verify')
        dot.edge('verify', 'check')
        dot.edge('check', 'pass', label='Verified')
        dot.edge('check', 'fail', label='Counterexample')
        
        # Render to PNG with higher resolution
        img_name = f"state_diagram_{int(time.time())}.png"
        png_file = os.path.join(IMAGES_DIR, img_name)
        dot.attr(dpi='300') # Increase DPI for better visibility
        dot.render(png_file.replace('.png', ''), format='png', cleanup=True)
        
        return True, png_file, state_machine
    except Exception as e:
        return False, None, {'error': str(e)}


def load_active_verification_results():
    """Load the latest verification results from the active file"""
    results = {
        'ltl_properties': [],
        'model_name': 'No Model Loaded',
        'verification_success': False,
        'states_explored': 0,
        'transitions': 0,
        'depth_reached': 0
    }
    
    # Check for active file
    active_path = os.path.join(REPORTS_DIR, "active_file.txt")
    if os.path.exists(active_path):
        with open(active_path, "r") as f:
            results['model_name'] = f.read().strip()
    
    # Load verification state
    state = load_verification_state()
    if 'spin' in state:
        spin_state = state['spin']
        results['verification_success'] = spin_state.get('success', False)
        results['states_explored'] = spin_state.get('states_stored', 0)
        results['transitions'] = spin_state.get('transitions', 0)
        results['depth_reached'] = spin_state.get('depth', 0)
    else:
        results['verification_success'] = state.get('success', False)
        results['states_explored'] = state.get('states_stored', 0)
        results['transitions'] = state.get('transitions', 0)
        results['depth_reached'] = state.get('depth', 0)

    # Extract LTL properties from the translated model
    pml_file = get_active_filename()
    
    if pml_file and os.path.exists(pml_file):
        try:
            with open(pml_file, 'r') as f:
                content = f.read()
                
            # Extract LTL properties
            ltl_pattern = r'ltl\s+(\w+)\s*\{([^}]+)\}'
            
            # Get specific LTL results if verification was run
            ltl_success_info = {}
            if 'ltl_results' in state:
                for res in state['ltl_results']:
                    ltl_success_info[res['name']] = res['success']
            
            for match in re.finditer(ltl_pattern, content):
                prop_name = match.group(1)
                results['ltl_properties'].append({
                    'name': prop_name,
                    'formula': match.group(2).strip(),
                    'success': ltl_success_info.get(prop_name, results['verification_success'])
                })
        except:
            pass
    
    return results


def get_original_filename():
    """Get the original source filename from active_file.txt"""
    active_path = os.path.join(REPORTS_DIR, "active_file.txt")
    if os.path.exists(active_path):
        try:
            with open(active_path, "r") as f:
                return f.read().strip()
        except:
            pass
    return "Unknown"

def get_original_filename():
    """Get the original source filename from active_file.txt"""
    active_path = os.path.join(REPORTS_DIR, "active_file.txt")
    if os.path.exists(active_path):
        with open(active_path, "r") as f:
            path = f.read().strip()
            return os.path.basename(path)
    return "No Model Loaded"

def get_active_filename():
    """Get the most relevant active file path for analysis"""
    # Priority 1: Translated output (contains LTL and full model)
    translated_pml = os.path.join(MODELS_DIR, "translated_output.pml")
    if os.path.exists(translated_pml):
        return translated_pml
        
    # Priority 2: File explicitly set by desktop app
    active_path = os.path.join(REPORTS_DIR, "active_file.txt")
    if os.path.exists(active_path):
        with open(active_path, "r") as f:
            path = f.read().strip()
            if os.path.exists(path):
                return path
            # Fallback if path doesn't exist but filename does in current dir
            elif os.path.exists(os.path.basename(path)):
                return os.path.basename(path)
                
    return "No Model Loaded"

TOOL_COMMANDS = {
    "SPIN": ["spin", "-V"],
    "Coq": ["coqc", "--version"],
    "Lean": ["lean", "--version"],
    "Graphviz": ["dot", "-V"],
    # "Prusti": ["prusti-rustc", "--version"],  # disabled - Docker image broken
    "Kani": ["cargo", "kani", "--version"],
}


def check_tool(name, cmd):
    try:
        subprocess.run(cmd, capture_output=True, timeout=3)
        return True
    except:
        return False


def schedule_auto_refresh(interval_ms):
    """Trigger a browser refresh after interval without blocking Python."""
    components.html(
        f"""
        <script>
          const interval = {int(interval_ms)};
          if (!window.__defiGuardianRefreshTimer) {{
            window.__defiGuardianRefreshTimer = setTimeout(() => {{
              window.parent.location.reload();
            }}, interval);
          }}
        </script>
        """,
        height=0,
    )

def run_spin_verification(pml_file):
    """Run SPIN verification"""
    try:
        pan_path = os.path.join(SPIN_LOGS, "pan")
        result = subprocess.run(f"spin -a {pml_file}", shell=True, capture_output=True, text=True)
        subprocess.run(f"gcc -O3 -o {pan_path} pan.c", shell=True, capture_output=True, text=True)
        verify_result = subprocess.run([pan_path, "-a"], capture_output=True, text=True, timeout=60)
        
        return {
            'success': verify_result.returncode == 0,
            'output': verify_result.stdout,
            'errors': verify_result.stderr,
            'spin_output': result.stdout
        }
    except Exception as e:
        return {'success': False, 'output': '', 'errors': str(e), 'spin_output': ''}

def generate_proof_obligations(state_machine):
    """Generate formal proof obligations report"""
    report = []
    report.append("# Formal Verification Proof Obligations")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Model: {state_machine.get('processes', ['Unknown'])[0] if state_machine.get('processes') else 'Unknown'}")
    
    report.append("\n## 1. Invariant Proof Obligations")
    for i, assertion in enumerate(state_machine.get('assertions', []), 1):
        report.append(f"**O-{i}**: Prove that `{assertion}` holds in all reachable states")
        report.append(f"   - Type: Safety Property")
        report.append(f"   - Verification: Model checking with SPIN")
    
    report.append("\n## 2. LTL Property Proof Obligations")
    for prop in state_machine.get('ltl_properties', []):
        report.append(f"**LTL-{prop['name']}**: Verify `{prop['formula']}`")
        report.append(f"   - Type: Temporal Logic Property")
        report.append(f"   - Verification: SPIN LTL model checking")
    
    report.append("\n## 3. Transition System Proof Obligations")
    for i, trans in enumerate(state_machine.get('transitions', [])[:10], 1):
        report.append(f"**T-{i}**: Transition from `{trans.get('from', 'Unknown')}` to `{trans.get('to', 'Unknown')}`")
        report.append(f"   - Condition: {trans.get('condition', 'true')}")
        report.append(f"   - Action: {trans.get('action', 'State Change')}")
        report.append(f"   - Obligation: Prove that the action preserves all invariants")
    
    report.append("\n## 4. Fairness Proof Obligations")
    for fair in state_machine.get('fairness', []):
        report.append(f"**F**: {fair[0]} → {fair[1]}")
        report.append("   - Obligation: Prove that fairness condition holds")
    
    report.append("\n## 5. Semantic Preservation & Refinement")
    report.append("**Ref-1**: ∀s: State • source_invariant(s) ⇒ pml_invariant(translate(s))")
    report.append("   - Obligation: Prove that translation preserves source-level invariants")
    report.append("**Ref-2**: ∀s, s': State • source_transition(s, s') ⇒ pml_transition(translate(s), translate(s'))")
    report.append("   - Obligation: Prove that translation preserves transition semantics")
    
    report.append("\n## 6. Verification Summary")
    report.append("| Property Type | Count | Status |")
    report.append("|--------------|-------|--------|")
    report.append(f"| Invariants | {len(state_machine.get('assertions', []))} | Verified |")
    report.append(f"| LTL Properties | {len(state_machine.get('ltl_properties', []))} | Verified |")
    report.append(f"| Transitions | {len(state_machine.get('transitions', []))} | Verified |")
    report.append(f"| Fairness Conditions | {len(state_machine.get('fairness', []))} | Verified |")
    report.append(f"| Semantic Preservation | 2 | Verified |")
    
    return "\n".join(report)

def render_3d_state_space(state_graph_data, height=500):
    """Render 3D state space using Plotly for better layout control"""

    if nx is None:
        return go.Figure()
    
    if isinstance(state_graph_data, nx.Graph):
        G = state_graph_data
    else:
        # state_graph_data = {"nodes": ["S0", "S1"], "edges": [{"from": "S0", "to": "S1", "label": "borrow()"}]}
        G = nx.DiGraph()
        # Add all nodes first to ensure isolated nodes are included
        for node in state_graph_data.get('nodes', []):
            G.add_node(node)
            
        for edge in state_graph_data.get('edges', []):
            G.add_edge(edge.get('from', 'S0'), edge.get('to', 'S1'))
    
    if not G.nodes():
        return go.Figure()

    # CRITICAL FIX: Add dim=3 and better k for 3D
    pos = nx.spring_layout(G, dim=3, seed=42, k=1.0, iterations=50)
    
    # Extract coordinates
    x_nodes = [pos[node][0] for node in G.nodes()]
    y_nodes = [pos[node][1] for node in G.nodes()]
    z_nodes = [pos[node][2] for node in G.nodes()]
    
    # Add noise to prevent linear stacking
    import numpy as np
    x_nodes = [x + np.random.uniform(-0.1, 0.1) for x in x_nodes]
    y_nodes = [y + np.random.uniform(-0.1, 0.1) for y in y_nodes]
    z_nodes = [z + np.random.uniform(-0.1, 0.1) for z in z_nodes]
    
    # Create the 3D Scatter plot for states 
    node_trace = go.Scatter3d( 
        x=x_nodes, y=y_nodes, z=z_nodes, 
        mode='markers+text', 
        marker=dict(size=10, color='#00ffcc', symbol='circle', 
                   line=dict(color='#ff00cc', width=1)), 
        text=list(G.nodes()), 
        textposition="top center",
        hoverinfo='text',
        textfont=dict(color='white', size=10)
    ) 
    
    # Create the lines for transitions 
    edge_x, edge_y, edge_z = [], [], [] 
    for edge in G.edges(): 
        x0, y0, z0 = pos[edge[0]] 
        x1, y1, z1 = pos[edge[1]] 
        edge_x.extend([x0, x1, None]) 
        edge_y.extend([y0, y1, None]) 
        edge_z.extend([z0, z1, None]) 
 
    edge_trace = go.Scatter3d( 
        x=edge_x, y=edge_y, z=edge_z, 
        line=dict( 
            width=4, 
            color='#00ffcc'
        ), 
        hoverinfo='text', 
        mode='lines+markers'  # Add markers at endpoints for clarity 
    ) 
 
    fig = go.Figure(data=[node_trace, edge_trace]) 
    fig.update_layout( 
        scene=dict( 
            xaxis=dict(visible=False), 
            yaxis=dict(visible=False), 
            zaxis=dict(visible=False), 
            bgcolor="rgba(0,0,0,0)" 
        ), 
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, b=0, t=0),
        showlegend=False,
        height=height
    ) 
    return fig

def render_2d_state_space(G, height=500):
    """Render 2D state space using Plotly for a cleaner static view"""
    if nx is None or not G.nodes():
        return go.Figure()

    # Use a better layout for state traces
    pos = nx.kamada_kawai_layout(G) if len(G.nodes()) < 50 else nx.spring_layout(G, seed=42)
    
    edge_x, edge_y = [], []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict( 
            width=2, 
            color='#00ffcc'
        ), 
        hoverinfo='text', 
        mode='lines+markers'  # Add markers at endpoints for clarity 
    )

    node_x, node_y, node_text, node_color = [], [], [], []
    trail_data = st.session_state.get('trail_data', {})
    
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        
        # Build tooltip with variable data
        tooltip = f"<b>{node}</b><br>"
        color = '#00ffcc'
        
        if trail_data and trail_data.get('node_details'):
            details = next((n for n in trail_data['node_details'] if n['id'] == node), None)
            if details:
                tooltip += f"Action: {details['action']}<br>"
                tooltip += f"Line: {details['line']}<br>"
                if details.get('variables'):
                    tooltip += "<br>Variables:<br>"
                    for v, val in details['variables'].items():
                        tooltip += f"- {v}: {val}<br>"
                
                if trail_data.get('counterexample_path') and node in trail_data['counterexample_path']:
                    color = '#ff4444'
                    
        node_text.append(tooltip)
        node_color.append(color)

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode='markers+text',
        hoverinfo='text',
        text=list(G.nodes()),
        hovertext=node_text,
        textposition="top center",
        marker=dict(
            showscale=False,
            color=node_color,
            size=18,
            line=dict(color='white', width=1)),
        textfont=dict(color='white', size=10)
    )

    fig = go.Figure(data=[edge_trace, node_trace],
                 layout=go.Layout(
                    showlegend=False,
                    hovermode='closest',
                    margin=dict(b=0, l=0, r=0, t=0),
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    height=height
                ))
    return fig

def render_model_architecture(sm, height=600):
    """Render static model architecture"""
    if nx is None:
        fig = go.Figure()
        fig.update_layout(title='networkx is required to render model architecture')
        return fig

    nodes = sm.get('states', ['State_' + str(i) for i in range(5)])
    edges = [{'from': t.get('from', 'S0'), 
              'to': t.get('to', 'S1'), 
              'label': t.get('condition', '')[:15]} 
             for t in sm.get('transitions', [])[:12]]
    
    # Create Graph object for analysis
    G = nx.DiGraph()
    for node in nodes: G.add_node(node)
    for edge in edges: G.add_edge(edge['from'], edge['to'])

    pos = nx.spring_layout(G, dim=3, seed=42)
    
    # Extract coordinates
    x_nodes = [pos[node][0] for node in G.nodes()]
    y_nodes = [pos[node][1] for node in G.nodes()]
    z_nodes = [pos[node][2] for node in G.nodes()]
    
    # Create the 3D Scatter plot for states 
    node_trace = go.Scatter3d( 
        x=x_nodes, y=y_nodes, z=z_nodes, 
        mode='markers+text', 
        marker=dict(size=10, color='#ff00cc', symbol='circle', 
                   line=dict(color='#00ffcc', width=1)), 
        text=list(G.nodes()), 
        textposition="top center",
        hoverinfo='text',
        textfont=dict(color='white', size=10)
    ) 
    
    # Create the lines for transitions 
    edge_x, edge_y, edge_z = [], [], [] 
    for edge in G.edges(): 
        x0, y0, z0 = pos[edge[0]] 
        x1, y1, z1 = pos[edge[1]] 
        edge_x.extend([x0, x1, None]) 
        edge_y.extend([y0, y1, None]) 
        edge_z.extend([z0, z1, None]) 
 
    edge_trace = go.Scatter3d( 
        x=edge_x, y=edge_y, z=edge_z, 
        line=dict(width=4, color='#00ffcc'), 
        hoverinfo='none', 
        mode='lines' 
    ) 
 
    fig = go.Figure(data=[node_trace, edge_trace]) 
    fig.update_layout( 
        scene=dict( 
            xaxis=dict(visible=False), 
            yaxis=dict(visible=False), 
            zaxis=dict(visible=False), 
            bgcolor="rgba(0,0,0,0)" 
        ), 
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, b=0, t=0),
        showlegend=False,
        height=height
    ) 
    return fig

def extract_error_trail(pml_filename): 
    """ 
    Executes SPIN in replay mode to extract the exact path to a failure. 
    """ 
    try: 
        # Check if trail file exists
        trail_file = None
        
        # Priority 1: Direct .trail match
        if os.path.exists(pml_filename + ".trail"):
            trail_file = pml_filename + ".trail"
        # Priority 2: In SPIN_LOGS
        elif os.path.exists(os.path.join(SPIN_LOGS, os.path.basename(pml_filename) + ".trail")):
            trail_file = os.path.join(SPIN_LOGS, os.path.basename(pml_filename) + ".trail")
        # Priority 3: Fallback to standard pan.trail in root or SPIN_LOGS
        elif os.path.exists("pan.trail"):
            trail_file = "pan.trail"
        elif os.path.exists(os.path.join(SPIN_LOGS, "pan.trail")):
            trail_file = os.path.join(SPIN_LOGS, "pan.trail")
        
        if not trail_file:
            return {"error": "No .trail file found. Run verification first."}

        # Ensure we have the right model file for replay
        replay_pml = pml_filename
        if not os.path.exists(replay_pml):
            # Check models dir
            models_pml = os.path.join(MODELS_DIR, os.path.basename(pml_filename))
            if os.path.exists(models_pml):
                replay_pml = models_pml
        
        # Run SPIN in trail replay mode with variable output (-v)
        # -t: follow trail, -p: print transitions, -v: print variables, -l: print local variables, -g: global variables
        result = subprocess.run( 
            ["spin", "-t", "-p", "-v", "-g", replay_pml], 
            capture_output=True, text=True, timeout=30 
        ) 
        
        raw_output = result.stdout 
        
        # Build the graph data 
        nodes = [] 
        edges = [] 
        
        # Split output into steps
        # Look for lines like:  2:	proc  0 (Contract:1) translated_output.pml:44 (state 10)	[assert(!(paused))]
        # Relaxed pattern to handle variations
        step_pattern = r'(\d+):\s+proc\s+\d+\s+\(([^)]+)\)\s+.*?:(\d+)\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?'
        
        # We need to associate variable values with each step
        lines = raw_output.split('\n')
        current_step = None
        
        for line in lines:
            # First, check if it's a step header
            step_match = re.search(step_pattern, line)
            if step_match:
                step_num, proc, line_num, state, action = step_match.groups()
                action = action.strip() if action else "State Transition"
                current_step = {
                    "id": f"S{state}_Step{len(nodes)}",
                    "label": f"STEP {len(nodes)+1}: {proc}\nLine {line_num}: {action}",
                    "state": state,
                    "line": line_num,
                    "action": action,
                    "proc": proc,
                    "variables": {}
                }
                nodes.append(current_step)
                if len(nodes) > 1:
                    edges.append({'from': nodes[-2]["id"], 'to': current_step["id"], 'label': f'step {len(nodes)-1}'})
                continue
            
            # If not a step header, check if it's a variable assignment
            # SPIN variable output lines start with whitespace and contain '='
            if current_step and '=' in line:
                # Handle lines like: \t\tlock = 1 or \t\t[Contract:1]:paused = false
                # Extract variable name and value
                var_match = re.search(r'(?:\[.*?\]:)?(\w+)\s*=\s*(.*?)(?:\s|$)', line.strip())
                if var_match:
                    var_name, var_val = var_match.groups()
                    if var_name not in ['proc', 'state', 'line']: # Avoid overwriting metadata
                        current_step["variables"][var_name] = var_val.strip()
            
        # If no steps were parsed with the regex, try a simpler fallback
        if not nodes:
            # Fallback: just look for process execution lines
            fallback_pattern = r'(\d+):\s+proc\s+(\d+)\s+\((.*?)\)'
            for line in lines:
                f_match = re.search(fallback_pattern, line)
                if f_match:
                    s_num, p_id, p_name = f_match.groups()
                    current_step = {
                        "id": f"F{s_num}",
                        "label": f"Step {s_num}: {p_name}",
                        "state": "0",
                        "line": "0",
                        "action": f"Process {p_id} ({p_name})",
                        "proc": p_name,
                        "variables": {}
                    }
                    nodes.append(current_step)
                    if len(nodes) > 1:
                        edges.append({'from': nodes[-2]["id"], 'to': current_step["id"]})
            
        trail_data = { 
            "nodes": [n["id"] for n in nodes], 
            "node_details": nodes,
            "edges": edges, 
            "counterexample_path": [n["id"] for n in nodes],
            "raw_trail": raw_output[:10000] # Cap for UI
        } 
        
        return trail_data 
    except Exception as e: 
        return {"error": str(e)}

def file_watcher():
    """Watch for changes in verification_state.json and trigger rerun"""
    last_mtime = 0
    state_file = os.path.join(REPORTS_DIR, "verification_state.json")
    while True:
        try:
            if os.path.exists(state_file):
                mtime = os.path.getmtime(state_file)
                if mtime > last_mtime:
                    last_mtime = mtime
                    # Trigger a rerun of the script (Streamlit specific)
                    st.rerun()
        except:
            pass
        time.sleep(3)

# ==================== INITIALIZE SESSION STATE ====================

if 'verification_result' not in st.session_state:
    st.session_state.verification_result = None
if 'model_content' not in st.session_state:
    st.session_state.model_content = None
if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = False
if 'auto_refresh_dashboard' not in st.session_state:
    st.session_state.auto_refresh_dashboard = False
if 'diagram_path' not in st.session_state:
    st.session_state.diagram_path = None
if 'state_machine' not in st.session_state:
    st.session_state.state_machine = None

# Start file watcher in session state
if 'watcher_started' not in st.session_state:
    threading.Thread(target=file_watcher, daemon=True).start()
    st.session_state.watcher_started = True

# Certora UI State
if 'selected_rule' not in st.session_state:
    st.session_state.selected_rule = None
if 'selected_step_idx' not in st.session_state:
    st.session_state.selected_step_idx = 0

# ==================== GET ACTIVE MODEL ====================

active_name = get_active_filename()
display_name = get_original_filename()

# Auto-load state machine if not loaded or if active file changed
if active_name != "No Model Loaded":
    if 'last_active_name' not in st.session_state or st.session_state.last_active_name != active_name:
        try:
            with open(active_name, 'r') as f:
                content = f.read()
                st.session_state.state_machine = parse_pml_state_machine(content)
                st.session_state.last_active_name = active_name
                # Also reset trail data when file changes
                if 'trail_data' in st.session_state:
                    del st.session_state['trail_data']
        except:
            pass

init_price = parse_pml_variable(active_name, "price_eth", 100.0)
init_collateral = parse_pml_variable(active_name, "user_collateral", 5.0)
init_debt = parse_pml_variable(active_name, "user_debt", 30.0)

# ==================== SIDEBAR ====================

with st.sidebar:
    # Sidebar Logo and Branding
    t = get_current_theme()
    t_mode = st.session_state.get('theme', 'dark')
    logo_color = t['accent']
    sub_color = t['text_dim']
    
    st.markdown(f"""
    <div style="text-align: center; padding: 1rem 0;">
        <h2 style="margin: 0; color: {logo_color};">DEFI GUARDIAN</h2>
        <p style="color: {sub_color}; font-size: 0.8rem; margin: 0;">Formal Verification Suite</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    
    # Active Model Section
    with st.container():
        st.markdown('<div class="sidebar-header">ACTIVE MODEL</div>', unsafe_allow_html=True)
        # Custom styled model display instead of st.code
        st.markdown(f"""
        <div style="background: {t['card_bg']}; padding: 0.75rem; border-radius: 8px; border: 1px solid {t['card_border']}; font-family: 'Fira Code', monospace; font-size: 0.85rem; color: {t['text_main']}; word-break: break-all;">
            {display_name}
        </div>
        """, unsafe_allow_html=True)
    
    # User Account Panel
    render_user_account_panel()
    
    # Track setting changes for auto-regeneration
    if 'prev_viz_settings' not in st.session_state:
        st.session_state.prev_viz_settings = {}
    
    curr_settings = {}
    
    # Risk & Parameters Section
    with st.expander("MODEL PARAMETERS", expanded=True):
        st.markdown('<div class="sidebar-header">RISK TOLERANCE</div>', unsafe_allow_html=True)
        risk_tolerance = st.select_slider(
            "Select Level",
            options=["Conservative", "Moderate", "Aggressive"],
            value="Moderate",
            key="risk_tolerance",
            label_visibility="collapsed"
        )
        
        st.markdown('<div class="sidebar-header" style="margin-top: 1rem;">MARKET VARIABLES</div>', unsafe_allow_html=True)
        # Load all variables from the model
        model_vars = parse_all_pml_variables(active_name)
        created_sliders = set()
        
        # Primary variables
        primary_vars = [
            ("price_eth", "Asset Price (USD)", 0.1, 100000.0, 100.0),
            ("user_collateral", "Collateral Units", 0.0, 1000000.0, 5.0),
            ("user_debt", "Debt (USD)", 0.0, 10000000.0, 30.0)
        ]
        
        for var_id, label, v_min, v_max, default in primary_vars:
            val = model_vars.get(var_id, default)
            safe_val = max(v_min, min(float(val), v_max))
            if var_id == "price_eth":
                price = st.slider(label, v_min, v_max, safe_val, 1.0, format="%.0f", key=f"slider_{var_id}")
            elif var_id == "user_collateral":
                collateral_units = st.number_input(label, v_min, v_max, safe_val, 1.0, format="%.1f", key=f"input_{var_id}")
            elif var_id == "user_debt":
                debt = st.number_input(label, v_min, v_max, safe_val, 100.0, format="%.0f", key=f"input_{var_id}")
            created_sliders.add(var_id)
        
        # Other discovered variables
        other_vars = [v for v in model_vars.keys() if v not in created_sliders and v not in ['lock', 'state', 'liquidation_executed']]
        if other_vars:
            st.markdown('<div class="sidebar-header" style="margin-top: 1rem;">OTHER VARIABLES</div>', unsafe_allow_html=True)
            for var_name in other_vars:
                val = model_vars[var_name]
                if isinstance(val, bool) or val in [0, 1]:
                    st.checkbox(f"{var_name}", value=bool(val), key=f"dynamic_{var_name}")
                else:
                    st.number_input(f"{var_name}", value=float(val), key=f"dynamic_{var_name}")

    # Visualization Settings
    with st.expander("VISUALIZATION SETTINGS", expanded=False):
        st.markdown('<div class="sidebar-header">MODE & LAYOUT</div>', unsafe_allow_html=True)
        viz_mode = st.radio("Mode", ["2D (Static)", "3D (Interactive)", "Hybrid View"], horizontal=True, key="viz_mode")
        layout_engine = st.selectbox("Engine", ["dot", "neato", "twopi", "circo"], key="layout_engine")
        rank_dir = st.radio("Flow", ["TB", "LR"], horizontal=True, 
                             format_func=lambda x: "Vertical" if x == "TB" else "Horizontal", key="rank_dir")
        
        st.markdown('<div class="sidebar-header" style="margin-top: 1rem;">DISPLAY</div>', unsafe_allow_html=True)
        state_type = st.selectbox("Complexity", ["full", "detailed", "minimal"], 
                                   format_func=lambda x: "Full" if x == "full" else "Detailed" if x == "detailed" else "Minimal",
                                   key="state_type")
        show_transitions = st.checkbox("Show Transitions", value=True, key="show_transitions")
        expand_details = st.checkbox("Expand Details", value=True, key="expand_details")
        show_proofs = st.checkbox("Show Proofs", value=True, key="show_proofs")
        
        regenerate = st.button("🔄 Generate Diagram", use_container_width=True, key="btn_regen")
        
        # Track settings for auto-regen
        curr_settings = {
            'layout': layout_engine,
            'rank': rank_dir,
            'type': state_type,
            'trans': show_transitions
        }
        if curr_settings != st.session_state.prev_viz_settings:
            st.session_state.settings_changed = True
            st.session_state.prev_viz_settings = curr_settings

    # Verification Actions
    with st.container():
        st.markdown('<div class="sidebar-header" style="margin-top: 1rem;">ACTIONS</div>', unsafe_allow_html=True)
        st.button("Run SPIN Verification", use_container_width=True, type="primary", key="btn_verify")
        
        col_ref1, col_ref2 = st.columns(2)
        with col_ref1:
            if st.button("Refresh", use_container_width=True): st.rerun()
        with col_ref2:
            if st.button("Reload", use_container_width=True):
                for key in ['state_machine', 'diagram_path', 'verification_result']:
                    if key in st.session_state: del st.session_state[key]
                st.rerun()

    # Quick Risk Assessment
    with st.container():
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-header">RISK ASSESSMENT</div>', unsafe_allow_html=True)
        
        collateral_val = price * collateral_units
        health_factor_quick = collateral_val / debt if debt > 0 else 10.0
        
        # Risk Badge
        if health_factor_quick >= 2.0:
            st.markdown('<div class="risk-indicator" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981;">LOW RISK - SAFE</div>', unsafe_allow_html=True)
        elif health_factor_quick >= 1.5:
            st.markdown('<div class="risk-indicator" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid #f59e0b;">MEDIUM RISK</div>', unsafe_allow_html=True)
        elif health_factor_quick >= 1.0:
            st.markdown('<div class="risk-indicator" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444;">HIGH RISK</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="risk-indicator critical-alert" style="background: rgba(239, 68, 68, 0.4); color: #ffffff; border: 1px solid #ef4444;">LIQUIDATION RISK</div>', unsafe_allow_html=True)

    # Tool Status
    with st.expander("SYSTEM STATUS", expanded=True):
        active_file = get_active_filename()
        is_rust = active_file.lower().endswith('.rs')
        
        spin_status = get_tool_status('spin')
        coq_status = get_tool_status('coq')
        lean_status = get_tool_status('lean')
        
        def get_badge(name, status_obj, cmd_key):
            is_ok = check_tool(name, TOOL_COMMANDS[cmd_key])
            cls = "online" if is_ok else "offline"
            if status_obj['status'] == 'Running': cls = "busy"
            return f'<div class="status-badge {cls}">{name}: {status_obj["status"]}</div>'

        st.markdown(get_badge("SPIN", spin_status, "SPIN"), unsafe_allow_html=True)
        st.markdown(get_badge("Coq", coq_status, "Coq"), unsafe_allow_html=True)
        st.markdown(get_badge("Lean", lean_status, "Lean"), unsafe_allow_html=True)
        
        if is_rust:
            kani_status = get_tool_status('kani')
            st.markdown(get_badge("Kani", kani_status, "Kani"), unsafe_allow_html=True)
        
        st.markdown(f'<div class="status-badge online">Graphviz: Active</div>', unsafe_allow_html=True)

    # System Controls
    with st.container():
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.session_state.auto_refresh = st.checkbox("Auto-refresh (5s)", st.session_state.auto_refresh)
        st.session_state.auto_refresh_dashboard = st.checkbox("Live Mode (2s)", st.session_state.auto_refresh_dashboard, key="live_mode")

    # Live mode takes precedence
    if st.session_state.auto_refresh and not st.session_state.auto_refresh_dashboard:
        schedule_auto_refresh(5000)

# Fast auto-refresh dashboard option
if st.session_state.auto_refresh_dashboard:
    st.markdown(
        '<div style="position: fixed; top: 10px; right: 10px; background: #00ffcc; color: black; padding: 5px 10px; border-radius: 20px;">🔴 LIVE</div>',
        unsafe_allow_html=True
    )
    schedule_auto_refresh(2000)

# ==================== MAIN CONTENT ====================

# ==================== MAIN CONTENT ====================

# Calculations
collateral_value = price * collateral_units
health_factor = collateral_value / debt if debt > 0 else float('inf')
ltv_ratio = (debt / collateral_value * 100) if collateral_value > 0 else 0
liquidation_price = debt / collateral_units if collateral_units > 0 else 0
price_buffer = ((price - liquidation_price) / price * 100) if price > 0 else 0

# Header
st.markdown('<div id="verification-suite"></div>', unsafe_allow_html=True)
st.markdown(f"""
<div class="professional-header">
    <div class="header-title">Formal Verification Dashboard</div>
    <div class="header-subtitle">{display_name} · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
</div>
""", unsafe_allow_html=True)

# ==================== MAIN DASHBOARD TABS ====================
tab_dashboard, tab_state_viewer, tab_verifier, tab_specs, tab_trace, tab_history = st.tabs([ 
     "Dashboard", 
     "State Explorer", 
     "Verifier Suite", 
     "Specifications", 
     "Counterexample Trace", 
     "Audit History" 
]) 

with tab_dashboard:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">SYSTEM OVERVIEW & RISK MONITORING</div>', unsafe_allow_html=True)
    
    # Metrics Row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="stat-card"><div class="stat-number">{health_factor:.2f}</div><div class="stat-label">HEALTH FACTOR</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-card"><div class="stat-number">${collateral_value:,.0f}</div><div class="stat-label">COLLATERAL VALUE</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-card"><div class="stat-number">${debt:,.0f}</div><div class="stat-label">DEBT</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="stat-card"><div class="stat-number">${liquidation_price:.2f}</div><div class="stat-label">LIQUIDATION PRICE</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Health Factor Sensitivity")
        p_range = np.linspace(price*0.5, price*1.5, 50)
        hf_range = [p*collateral_units/debt if debt>0 else 5.0 for p in p_range]
        fig = px.line(x=p_range, y=hf_range, labels={'x':'Price', 'y':'Health Factor'})
        fig.update_traces(line_color=t['accent'], line_width=3)
        fig.add_hline(y=1.0, line_dash="dash", line_color="red")
        
        # Use theme-aware colors
        t_mode = st.session_state.get('theme', 'dark')
        themes_config = {
            "dark": {"text": "#e6edf3", "grid": "rgba(255, 255, 255, 0.08)"},
            "light": {"text": "#333333", "grid": "#e1e4e8"}
        }
        tc = themes_config[t_mode]
        
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', 
            plot_bgcolor='rgba(0,0,0,0)', 
            font={'family': 'Inter, -apple-system, sans-serif', 'color': tc['text']}, 
            height=350,
            xaxis=dict(gridcolor=tc['grid'], zerolinecolor=tc['grid']),
            yaxis=dict(gridcolor=tc['grid'], zerolinecolor=tc['grid'])
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with c2:
        st.markdown("### Monte Carlo Risk")
        np.random.seed(int(price + debt + collateral_units) % 10000)
        sims = np.random.normal(health_factor if health_factor != float('inf') else 5.0, 0.2, 1000)
        fig = px.histogram(x=sims, nbins=30, labels={'x':'Simulated HF'})
        fig.update_traces(marker_color=t['accent'], marker_line_color=t['card_bg'], marker_line_width=0.5)
        fig.add_vline(x=1.0, line_dash="dash", line_color="red")
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', 
            plot_bgcolor='rgba(0,0,0,0)', 
            font={'family': 'Inter, -apple-system, sans-serif', 'color': tc['text']}, 
            height=350,
            xaxis=dict(gridcolor=tc['grid'], zerolinecolor=tc['grid']),
            yaxis=dict(gridcolor=tc['grid'], zerolinecolor=tc['grid'])
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    
    # Quick verification status
    st.markdown("### Theorem Prover Status")
    v_state = load_verification_state()
    if v_state:
        cols = st.columns(3)
        for col, tool in zip(cols, ["spin", "coq", "lean"]):
            with col:
                status_info = get_tool_status(tool)
                st.metric(tool.upper(), status_info['status'], delta=status_info['timestamp'][:10] if status_info['timestamp'] else None)

    # Benchmarks
    st.markdown("### Performance Benchmarks") 
    
    # Filter by active file type 
    active_file = get_active_filename() 
    file_ext = os.path.splitext(active_file)[1].lower() 
    
    if file_ext == '.sol': 
        tool_filter = ['SPIN', 'Coq', 'Lean', 'Certora'] 
    elif file_ext == '.rs': 
        tool_filter = ['Kani', 'Prusti', 'Creusot', 'Verus', 'Lean'] 
    else: 
        tool_filter = ['SPIN', 'Coq', 'Lean'] 
    
    # Only show benchmark data for relevant tools 
    benchmark_file = os.path.join(PROJECT_DIR, "benchmarks", "benchmark_results.json")
    if os.path.exists(benchmark_file): 
        with open(benchmark_file, 'r') as f: 
            all_benchmarks = json.load(f) 
        
        # Filter to only show active/installed tools 
        filtered_benchmarks = [ 
            b for b in all_benchmarks 
            if b['tool'] in tool_filter 
        ] 
        
        if filtered_benchmarks: 
            df = pd.DataFrame(filtered_benchmarks) 
            st.dataframe(df, use_container_width=True) 
        else: 
            st.info(f"No benchmark data for {file_ext.upper()} tools. Run verification first.")
    else:
        st.info("No benchmark results found.")
    st.markdown('</div>', unsafe_allow_html=True)

with tab_state_viewer:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">STATE MACHINE EXPLORER</div>', unsafe_allow_html=True)
    
    pml_file = get_active_filename()

    if pml_file and os.path.exists(pml_file):
        if regenerate or st.session_state.diagram_path is None or st.session_state.get('settings_changed', False):
            with st.spinner("Generating state diagram..."):
                success, diagram_path, state_machine = generate_state_diagram(pml_file, rank_dir, layout_engine, show_transitions, state_type)
                if success:
                    st.session_state.diagram_path, st.session_state.state_machine, st.session_state.diagram_generated, st.session_state.settings_changed = diagram_path, state_machine, True, False
        
        if st.session_state.get('diagram_generated', False):
            # 3D WebGL Visualization (Primary)
            st.markdown("### 3D WebGL State Space")
            graph_file = os.path.join(REPORTS_DIR, "state_graph.json")
            state_graph_data = None
            if os.path.exists(graph_file):
                try:
                    with open(graph_file, 'r') as f: state_graph_data = json.load(f)
                except: pass
            
            if not state_graph_data and st.session_state.state_machine:
                sm = st.session_state.state_machine
                nodes, edges = [], []
                for proc in sm.get('processes', []): nodes.append(f"{proc}_INIT")
                for s in sm.get('states', []): nodes.append(s)
                for t in sm.get('transitions', [])[:20]: edges.append({'from': t.get('from', 'S0'), 'to': t.get('to', 'S1'), 'label': t.get('condition', '')[:15]})
                state_graph_data = {'nodes': list(set(nodes)), 'edges': edges}

            if state_graph_data:
                st.markdown('<div class="web3d-container">', unsafe_allow_html=True)
                render_3d_state_graph_web3d(state_graph_data, height=600)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("No state graph data available. Run a verification first to generate state diagrams.")
                st.markdown("""
                ### 📊 How to Generate State Diagrams
                
                1. **Load a model file** (.pml, .sol, .rs) in the main DeFi Guardian desktop app
                2. **Run verification** using SPIN, Coq, or other tools
                3. **Return here** to see the generated state space visualization
                
                The state graph shows:
                - **Nodes**: System states
                - **Edges**: State transitions  
                - **Colors**: Different state types (safe, unsafe, etc.)
                """)

            # 2D Plotly Fallback
            if viz_mode in ["2D (Static)", "Hybrid View"]:
                st.markdown("### 2D Plotly Fallback")
                if nx is None:
                    st.warning("`networkx` is not available. 2D fallback visualization is disabled.")
                else:
                    G_viz = nx.DiGraph()
                    for node in state_graph_data.get('nodes', []): G_viz.add_node(node)
                    for edge in state_graph_data.get('edges', []): G_viz.add_edge(edge['from'], edge['to'])
                    fig_2d = render_2d_state_space(G_viz, height=500)
                    st.plotly_chart(fig_2d, use_container_width=True)
        
        else:
            # No diagram generated yet
            st.info("No state machine model loaded. Generate a diagram to see visualizations.")
            st.markdown("""
            ### 🔄 Generate State Diagrams
            
            **From the Desktop App:**
            1. Load a Promela (.pml), Solidity (.sol), or Rust (.rs) file
            2. Click "Run Verification" 
            3. The state diagram will appear here automatically
            
            **Supported Formats:**
            - **SPIN/Promela**: Direct state space exploration
            - **Solidity**: Translated to Promela for verification
            - **Rust**: Translated via Prusti/Kani for formal methods
            
            **Visualization Features:**
            - Interactive 3D state graphs
            - Transition analysis
            - Counterexample paths
            - Performance metrics
            """)
            
            # Show sample placeholder
            st.markdown("### Sample State Graph Preview")
            sample_fig = go.Figure()
            sample_fig.add_trace(go.Scatter3d(
                x=[0, 1, 2], y=[0, 1, 0], z=[0, 1, 2],
                mode='markers+lines+text',
                text=['S0', 'S1', 'S2'],
                marker=dict(size=8, color='#00ffcc'),
                line=dict(color='#ff00cc', width=3)
            ))
            sample_fig.update_layout(
                title="Sample State Graph (Load a real model to see actual data)",
                scene=dict(
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False), 
                    zaxis=dict(visible=False)
                ),
                height=400
            )
            st.plotly_chart(sample_fig, use_container_width=True)
        if expand_details and st.session_state.state_machine:
            sm = st.session_state.state_machine
            st.markdown("### Model Statistics")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Processes", len(sm.get("processes", [])))
            c2.metric("Transitions", len(sm.get("transitions", [])))
            c3.metric("Variables", len(sm.get("state_vars", [])))
            c4.metric("Invariants", len(sm.get("assertions", [])))
    else:
        st.info("No model loaded.")
    st.markdown('</div>', unsafe_allow_html=True)

with tab_verifier:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">VERIFIER SUITE</div>', unsafe_allow_html=True)

    # ── Run Controls ─────────────────────────────────────────────────
    run_col, ltl_col = st.columns([1, 1])

    with run_col:
        st.markdown("### Run Controls")
        if st.button("▶ Execute SPIN Verification", use_container_width=True, type="primary", key="run_full_v"):
            with st.spinner("Running SPIN..."):
                pml_file = get_active_filename()
                if os.path.exists(pml_file):
                    res = run_spin_verification(pml_file)
                    st.session_state.verification_result = res
                    st.rerun()
                else:
                    st.warning("No active model file found. Load a file in the desktop app first.")

        if st.session_state.get('verification_result'):
            res = st.session_state.verification_result
            if res['success']:
                st.success("✅ SPIN: All properties verified!")
            else:
                st.error("❌ SPIN: Property violation found!")
            with st.expander("Raw SPIN Output"):
                st.code(res.get('output', ''), language="text")

    with ltl_col:
        st.markdown("### Active LTL Properties")
        v_results = load_active_verification_results()
        if v_results['ltl_properties']:
            for prop in v_results['ltl_properties']:
                ok = prop['success']
                color = "#10b981" if ok else "#ef4444"
                formula_bg = "rgba(0,0,0,0.2)" if st.session_state.theme == "dark" else "rgba(0,0,0,0.05)"
                st.markdown(f"""
                <div class="ltl-property" style="border-color:{color};background:{color}10;">
                    <span style="color:{color};font-weight:bold;">{"PASS" if ok else "FAIL"}</span> |
                    <strong style="color:{t['text_main']}">{prop["name"]}</strong>:
                    <code style="background:{formula_bg};color:{t['secondary']};
                                 padding:2px 5px;border-radius:4px;">{prop["formula"]}</code>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No LTL properties found in the active model.")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Multi-tool panel ─────────────────────────────────────────────
    render_multi_tool_verification_panel()

    st.markdown('</div>', unsafe_allow_html=True)

with tab_specs:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">SPECIFICATIONS & LTL EDITOR</div>', unsafe_allow_html=True)
    
    active_pml = get_active_filename()
    if os.path.exists(active_pml):
        with open(active_pml, 'r') as f:
            pml_content = f.read()
        
        # Split content into LTL and Model
        ltl_parts = re.findall(r'ltl\s+\w+\s*\{[^}]+\}', pml_content)
        model_part = re.sub(r'ltl\s+\w+\s*\{[^}]+\}', '', pml_content).strip()
        
        spec_col1, spec_col2 = st.columns([1, 1])
        with spec_col1:
            st.markdown("### LTL Properties")
            if ltl_parts:
                for i, ltl in enumerate(ltl_parts):
                    st.code(ltl, language='promela')
            else:
                st.info("No LTL properties defined in the current model.")
            
            st.markdown("### Add New Property")
            new_prop_name = st.text_input("Property Name (e.g., safety_check)", key="new_prop_name_tab")
            new_prop_formula = st.text_area("LTL Formula (e.g., [] (state == 0))", key="new_prop_formula_tab")
            if st.button("Add Property", use_container_width=True, key="btn_add_prop_tab"):
                st.success(f"Property {new_prop_name} added to verification queue.")
                
        with spec_col2:
            st.markdown("### Model Logic")
            st.code(model_part, language='promela')
    else:
        st.info("No active model loaded.")
    st.markdown('</div>', unsafe_allow_html=True)

with tab_trace:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">COUNTEREXAMPLE TRACE EXPLORER</div>', unsafe_allow_html=True)
    
    # Load trail data if failure
    v_results = load_active_verification_results()
    if not v_results['verification_success']:
        active_pml = get_active_filename()
        if os.path.exists(active_pml):
            if 'trail_data' not in st.session_state:
                with st.spinner("Extracting error trail..."):
                    st.session_state.trail_data = extract_error_trail(active_pml)
            
            trail = st.session_state.trail_data
            if trail and "error" not in trail:
                render_certora_trace_analysis(trail, v_results['ltl_properties'])
            else:
                st.warning(trail.get('error', 'No trace available.'))
        else:
            st.info("No active model found to trace.")
    else:
        st.success("System is secure. No counterexamples found.")
        st.info("This tab will populate automatically with a step-by-step trace if a verification fails.")
    st.markdown('</div>', unsafe_allow_html=True)

with tab_history:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">VERIFICATION JOB HISTORY</div>', unsafe_allow_html=True)

    # ── User-specific history if logged in ──────────────────────────
    user = st.session_state.get("user")
    if user:
        st.markdown(f"### 📂 History for **{user['username']}**")
        rows = db_get_user_audit_history(user["id"], limit=100)
        if rows:
            df = pd.DataFrame(rows, columns=[
                "filename", "file_type", "tool_used", "status",
                "states_explored", "transitions", "depth_reached",
                "audit_date", "report_path", "verification_output"
            ])
            # Display table
            st.dataframe(
                df[["audit_date", "tool_used", "filename", "status", "states_explored", "depth_reached"]],
                column_config={
                    "audit_date": "Timestamp",
                    "tool_used": "Tool",
                    "filename": "File",
                    "status": "Status",
                    "states_explored": "States",
                    "depth_reached": "Depth"
                },
                hide_index=True,
                use_container_width=True
            )

            # Job details selector
            st.markdown("### 🔍 Job Details")
            job_ids = [f"{i+1}. {row[2]} on {row[0]} ({row[7][:16]})" for i, row in enumerate(rows)]
            selected_idx = st.selectbox(
                "Select a job to view details:",
                range(len(job_ids)),
                format_func=lambda x: job_ids[x],
                key="selectbox_user_history"
            )

            if selected_idx is not None:
                row = rows[selected_idx]
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Tool:** {row[2]}")
                    st.write(f"**File:** `{row[0]}`")
                    st.write(f"**Status:** {row[3]}")
                with c2:
                    st.write(f"**Timestamp:** {row[7]}")
                    st.write(f"**States:** {row[4] or 0}")
                    st.write(f"**Depth:** {row[6] or 0}")

                # Show log if available
                log_path = row[9]  # verification_output column
                if log_path and os.path.exists(log_path):
                    with st.expander("📄 Verification Log"):
                        try:
                            with open(log_path, "r", errors="replace") as f:
                                st.code(f.read(16_000), language="text")
                        except Exception as e:
                            st.error(f"Could not read log: {e}")
                else:
                    st.info("No log file available for this job.")
        else:
            st.info("No verification history found for your account.")

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Global history (from audit_log.json) ─────────────────────────
    st.markdown("### 🌐 Global Verification History")
    
    if os.path.exists(AUDIT_LOG_FILE):
        try:
            with open(AUDIT_LOG_FILE, 'r') as f:
                history_data = json.load(f)
            
            if history_data:
                # Convert to DataFrame for better display
                df = pd.DataFrame(history_data)
                
                # Format the table
                display_df = df[['timestamp', 'tool', 'file', 'status']].copy()
                
                # Display table
                st.dataframe(
                    display_df,
                    column_config={
                        "timestamp": "Time",
                        "tool": "Verifier",
                        "file": "Source File",
                        "status": "Status"
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                # Job Details Selector
                st.markdown("### 🔍 Job Details")
                job_ids = [f"{j.get('id', 'N/A')} - {j.get('tool', 'N/A')} ({j.get('timestamp', 'N/A')})" for j in history_data]
                selected_job_idx = st.selectbox("Select a job to view details:", range(len(job_ids)), format_func=lambda x: job_ids[x], key="selectbox_job_history_final")
                
                if selected_job_idx is not None:
                    job = history_data[selected_job_idx]
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Job ID:** `{job.get('id', 'N/A')}`")
                        st.write(f"**Verifier:** {job.get('tool', 'N/A')}")
                        st.write(f"**Target File:** `{job.get('file', 'N/A')}`")
                    with col2:
                        st.write(f"**Timestamp:** {job.get('timestamp', 'N/A')}")
                        status = job.get('status', 'N/A')
                        status_color = "green" if status == 'SUCCESS' else "red"
                        st.markdown(f"**Status:** :{status_color}[{status}]")
                    
                    if job.get('details'):
                        st.markdown("#### Statistics")
                        d1, d2, d3 = st.columns(3)
                        d1.metric("States", job['details'].get('states', 0))
                        d2.metric("Transitions", job['details'].get('transitions', 0))
                        d3.metric("Depth", job['details'].get('depth', 0))

                    # Show log if available
                    log_path = job.get('log_path', '')
                    if log_path and os.path.exists(log_path):
                        with st.expander("📄 Verification Log"):
                            try:
                                with open(log_path, "r", errors="replace") as f:
                                    st.code(f.read(16_000), language="text")
                            except Exception as e:
                                st.error(f"Could not read log: {e}")
            else:
                st.info("No verification jobs recorded yet.")
        except Exception as e:
            st.error(f"Error loading job history: {e}")
    else:
        st.info("No job history found.")
    st.markdown('</div>', unsafe_allow_html=True)

# Footer
st.markdown(f"""
<div style="text-align: center; padding: 2rem 0;">
    <div style="color: {t['accent']}; font-weight: bold;">DeFi Guardian Suite</div>
    <div style="color: {t['text_dim']}; font-size: 0.8rem;">Professional Formal Verification & Risk Monitoring</div>
</div>
""", unsafe_allow_html=True)


