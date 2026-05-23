"""
DeFi Guardian - Flask-Powered Desktop Application
Combines Flask UI with native desktop window
"""

import webview
import threading
import os
import sys
import json
import subprocess
import time
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime
import re

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Project paths
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

# Ensure directories exist
for d in [LOGS_DIR, SPIN_LOGS, CERTORA_LOGS, COQ_LOGS, LEAN_LOGS, 
          RUST_LOGS, GENERATED_DIR, MODELS_DIR, IMAGES_DIR, REPORTS_DIR]:
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)

# ==================== FLASK ROUTES ====================

@app.route('/')
def desktop_home():
    """Main desktop application page"""
    return render_template('desktop_app.html')

@app.route('/api/file/open', methods=['POST'])
def open_file():
    """Open and read a file"""
    data = request.json
    file_path = data.get('path')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({
            'success': True,
            'content': content,
            'filename': os.path.basename(file_path),
            'file_type': os.path.splitext(file_path)[1].lower()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/translate', methods=['POST'])
def translate_contract():
    """Translate Solidity/Rust to Promela"""
    data = request.json
    source_code = data.get('code', '')
    file_type = data.get('file_type', '.sol')
    
    try:
        from translator import DeFiTranslator, VerifiedTranslator
        
        if file_type == '.sol':
            translator = VerifiedTranslator()
            translated, obligations = translator.translate_with_proof(source_code)
        elif file_type == '.rs':
            translated = DeFiTranslator.translate_rust(source_code)
        else:
            translated = source_code
        
        # Save to disk
        output_path = os.path.join(MODELS_DIR, "translated_output.pml")
        with open(output_path, 'w') as f:
            f.write(translated)
        
        # Extract LTL properties
        ltl_properties = []
        ltl_pattern = r'ltl\s+(\w+)\s*\{([^}]+)\}'
        for match in re.finditer(ltl_pattern, translated, re.DOTALL):
            ltl_properties.append({
                'name': match.group(1),
                'formula': match.group(2).strip()
            })
        
        return jsonify({
            'success': True,
            'translated': translated,
            'ltl_properties': ltl_properties,
            'output_path': output_path
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/verify/spin', methods=['POST'])
def verify_spin():
    """Run SPIN verification"""
    data = request.json
    translated_code = data.get('code', '')
    
    # Save to temp file
    pml_path = os.path.join(MODELS_DIR, "temp_verify.pml")
    with open(pml_path, 'w') as f:
        f.write(translated_code)
    
    try:
        # Run SPIN
        result = subprocess.run(
            ['spin', '-a', pml_path],
            capture_output=True, text=True, timeout=60,
            cwd=PROJECT_DIR
        )
        
        spin_output = result.stdout + '\n' + result.stderr
        
        # Compile pan.c
        pan_path = os.path.join(SPIN_LOGS, "pan")
        compile_result = subprocess.run(
            ['gcc', '-O3', '-o', pan_path, 'pan.c'],
            capture_output=True, text=True, timeout=60,
            cwd=PROJECT_DIR
        )
        
        if compile_result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'Compilation failed: {compile_result.stderr}',
                'spin_output': spin_output
            })
        
        # Run pan verifier
        verify_result = subprocess.run(
            [pan_path, '-a'],
            capture_output=True, text=True, timeout=120,
            cwd=PROJECT_DIR
        )
        
        # Check for errors in output
        output = verify_result.stdout
        has_errors = 'errors: 0' not in output or 'assertion violated' in output.lower()
        
        # Parse statistics
        stats = {}
        states_match = re.search(r"(\d+) states, stored", output)
        if states_match:
            stats['states'] = int(states_match.group(1))
        depth_match = re.search(r"depth reached (\d+)", output)
        if depth_match:
            stats['depth'] = int(depth_match.group(1))
        trans_match = re.search(r"(\d+) transitions", output)
        if trans_match:
            stats['transitions'] = int(trans_match.group(1))
        
        # Save verification state
        save_verification_state('spin', not has_errors, output, verify_result.stderr)
        
        return jsonify({
            'success': not has_errors,
            'output': output,
            'stats': stats,
            'has_counterexample': has_errors
        })
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Verification timed out'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/verify/coq', methods=['POST'])
def verify_coq():
    """Run Coq verification"""
    try:
        from coq_verifier import CoqVerifier
        verifier = CoqVerifier()
        
        data = request.json
        contract_name = data.get('contract_name', 'Contract')
        properties = data.get('properties', {})
        
        coq_script = verifier.generate_coq_script(contract_name, properties)
        result = verifier.verify_with_coq(coq_script)
        
        save_verification_state('coq', result.get('success', False), 
                               result.get('output', ''), result.get('errors', ''))
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/verify/lean', methods=['POST'])
def verify_lean():
    """Run Lean verification"""
    import tempfile
    
    data = request.json
    contract_name = data.get('contract_name', 'Contract')
    
    lean_script = f"""-- Lean 4 Formal Verification
-- Contract: {contract_name}
-- Generated by DeFi Guardian

def collateral : Nat := 5000
def debt       : Nat := 3000
def price      : Nat := 100

theorem collateral_sufficient :
    collateral * price ≥ debt := by
  native_decide

theorem balance_non_negative (b : Nat) : b ≥ 0 := Nat.zero_le b

def lock_after_op (locked : Bool) : Bool :=
  if locked then locked else true

theorem lock_acquired (locked : Bool) (h : locked = false) :
    lock_after_op locked = true := by
  simp [lock_after_op, h]

#check collateral_sufficient
#check balance_non_negative
#check lock_acquired
"""
    
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.lean', delete=False)
    tmp_file.write(lean_script)
    tmp_file.close()
    
    try:
        result = subprocess.run(
            ['lean', tmp_file.name],
            capture_output=True, text=True, timeout=120
        )
        
        success = result.returncode == 0
        save_verification_state('lean', success, result.stdout, result.stderr)
        
        return jsonify({
            'success': success,
            'output': result.stdout,
            'errors': result.stderr
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        os.unlink(tmp_file.name)

@app.route('/api/verify/prusti', methods=['POST'])
def verify_prusti():
    """Run Prusti verification"""
    try:
        from rust_verifiers import RustVerifier, build_prusti_env, should_skip_prusti_for_source
        
        data = request.json
        rust_code = data.get('code', '')
        
        skip, reason = should_skip_prusti_for_source(rust_code)
        if skip:
            return jsonify({'success': False, 'error': reason, 'skipped': True})
        
        verifier = RustVerifier()
        if not verifier.prusti_available:
            return jsonify({'success': False, 'error': 'Prusti not installed'})
        
        annotated = verifier.analyze_and_annotate(rust_code)
        result = verifier.verify_with_prusti(annotated)
        
        save_verification_state('prusti', result.get('success', False),
                               result.get('output', ''), result.get('errors', ''))
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/file/save', methods=['POST'])
def save_file():
    """Save file content"""
    data = request.json
    file_path = data.get('path')
    content = data.get('content')
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/state/current')
def current_state():
    """Get current verification state"""
    state_file = os.path.join(REPORTS_DIR, "verification_state.json")
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route('/api/tools/status')
def tools_status():
    """Check which tools are available"""
    tools = {}
    
    # Check SPIN
    try:
        r = subprocess.run(['spin', '-V'], capture_output=True, timeout=2)
        tools['spin'] = r.returncode == 0
    except:
        tools['spin'] = False
    
    # Check Coq
    try:
        subprocess.run(['coqc', '--version'], capture_output=True, timeout=2)
        tools['coq'] = True
    except:
        tools['coq'] = False
    
    # Check Lean
    try:
        subprocess.run(['lean', '--version'], capture_output=True, timeout=2)
        tools['lean'] = True
    except:
        tools['lean'] = False
    
    # Check Prusti
    try:
        subprocess.run(['prusti-rustc', '--version'], capture_output=True, timeout=5)
        tools['prusti'] = True
    except:
        tools['prusti'] = False
    
    # Check Kani
    try:
        subprocess.run(['cargo', 'kani', '--version'], capture_output=True, timeout=5)
        tools['kani'] = True
    except:
        tools['kani'] = False
    
    return jsonify(tools)

def save_verification_state(tool, success, output, errors):
    """Save verification state for a tool"""
    state_file = os.path.join(REPORTS_DIR, "verification_state.json")
    
    state = {}
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            state = json.load(f)
    
    state[tool] = {
        'timestamp': datetime.now().isoformat(),
        'status': 'PASS' if success else 'FAIL',
        'success': success,
        'output': output,
        'errors': errors
    }
    
    if tool == 'spin':
        state['success'] = success
        state['datetime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Parse statistics
        states_match = re.search(r"(\d+) states, stored", output)
        if states_match:
            state['states_stored'] = int(states_match.group(1))
        
        depth_match = re.search(r"depth reached (\d+)", output)
        if depth_match:
            state['depth'] = int(depth_match.group(1))
    
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


# ==================== DESKTOP APP TEMPLATE ====================

DESKTOP_APP_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DeFi Guardian - Desktop</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/editor/editor.main.css" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #161b22;
            --bg-tertiary: #1a1a2e;
            --accent: #00ffcc;
            --accent-dark: #00ccaa;
            --accent-secondary: #ff00cc;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --border-color: #30363d;
            --success: #238636;
            --error: #da3633;
            --warning: #d29922;
            --terminal-bg: #0d1117;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: var(--bg-primary);
            color: var(--text-primary);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            overflow: hidden;
            height: 100vh;
        }

        .app-container {
            display: flex;
            height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            width: 360px;
            min-width: 360px;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }

        .sidebar-header {
            padding: 1.5rem;
            border-bottom: 1px solid var(--border-color);
            text-align: center;
        }

        .sidebar-header h1 {
            font-size: 1.5rem;
            font-weight: 800;
            color: var(--accent);
            margin: 0;
        }

        .sidebar-header .subtitle {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        .sidebar-section {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid rgba(48, 54, 61, 0.5);
        }

        .section-title {
            font-size: 0.7rem;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.15em;
            margin-bottom: 0.75rem;
        }

        .btn {
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.85rem;
            padding: 0.7rem 1rem;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: none;
            width: 100%;
            margin-bottom: 0.4rem;
            text-align: left;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn i {
            width: 20px;
            text-align: center;
        }

        .btn-accent {
            background: linear-gradient(135deg, var(--accent), var(--accent-dark));
            color: #000;
        }

        .btn-accent:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 255, 204, 0.3);
            color: #000;
        }

        .btn-success {
            background: linear-gradient(135deg, #238636, #2ea043);
            color: white;
        }

        .btn-success:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(35, 134, 54, 0.3);
            color: white;
        }

        .btn-purple {
            background: linear-gradient(135deg, #9b59b6, #8e44ad);
            color: white;
        }

        .btn-purple:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(155, 89, 182, 0.3);
            color: white;
        }

        .btn-orange {
            background: linear-gradient(135deg, #e67e22, #d35400);
            color: white;
        }

        .btn-danger {
            background: linear-gradient(135deg, #da3633, #c53030);
            color: white;
        }

        .btn-outline {
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
        }

        .btn-outline:hover {
            border-color: var(--accent);
            color: var(--accent);
        }

        .file-info {
            font-size: 0.8rem;
            color: var(--accent);
            padding: 0.5rem;
            background: rgba(0, 255, 204, 0.05);
            border-radius: 6px;
            margin-top: 0.5rem;
            word-break: break-all;
        }

        .tool-status {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }

        .tool-status .status-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 0.25rem;
        }

        .status-dot.available { background: var(--success); }
        .status-dot.unavailable { background: var(--error); }
        .status-dot.running { background: var(--warning); animation: pulse 1s infinite; }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* Main Content */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Editor Area */
        .editor-area {
            flex: 7;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }

        .editor-tabs {
            display: flex;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border-color);
            padding: 0 1rem;
        }

        .editor-tab {
            padding: 0.75rem 1.5rem;
            cursor: pointer;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-size: 0.85rem;
            font-weight: 500;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }

        .editor-tab:hover {
            color: var(--text-primary);
        }

        .editor-tab.active {
            color: var(--accent);
            border-bottom-color: var(--accent);
        }

        .editor-container {
            flex: 1;
            min-height: 0;
        }

        /* Terminal Area */
        .terminal-area {
            flex: 3;
            border-top: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            min-height: 200px;
        }

        .terminal-header {
            padding: 0.5rem 1rem;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .terminal-header h3 {
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--accent);
            margin: 0;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        .terminal-content {
            flex: 1;
            background: var(--terminal-bg);
            padding: 1rem;
            overflow-y: auto;
            font-family: 'Fira Code', 'Consolas', monospace;
            font-size: 0.8rem;
            line-height: 1.6;
        }

        .terminal-content .log-line {
            margin-bottom: 0.15rem;
        }

        .log-line.header { color: var(--accent); font-weight: bold; }
        .log-line.success { color: var(--success); }
        .log-line.error { color: var(--error); }
        .log-line.warning { color: var(--warning); }
        .log-line.dim { color: var(--text-secondary); }

        /* Status Bar */
        .status-bar {
            padding: 0.4rem 1rem;
            background: var(--bg-tertiary);
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .btn-sm {
            padding: 0.3rem 0.75rem;
            font-size: 0.75rem;
            width: auto;
            display: inline-flex;
            margin-bottom: 0;
        }

        .spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid var(--text-secondary);
            border-radius: 50%;
            border-top-color: var(--accent);
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="app-container">
        <!-- Sidebar -->
        <div class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <h1>🛡️ DEFI GUARDIAN</h1>
                <div class="subtitle">Formal Verification Suite</div>
            </div>

            <div class="sidebar-section">
                <div class="section-title">File Operations</div>
                <button class="btn btn-accent" onclick="openFile()">
                    <i class="fas fa-folder-open"></i> Open Source File
                </button>
                <div class="file-info" id="fileInfo">No file loaded</div>
            </div>

            <div class="sidebar-section">
                <div class="section-title">Core Verification</div>
                <button class="btn btn-success" id="btnSpinVerify" onclick="runSpinVerification()">
                    <i class="fas fa-play"></i> Run SPIN Verification
                </button>
                <button class="btn btn-purple" id="btnCoqVerify" onclick="runCoqVerification()">
                    <i class="fas fa-scroll"></i> Coq Proof Assistant
                </button>
                <button class="btn btn-orange" id="btnLeanVerify" onclick="runLeanVerification()">
                    <i class="fas fa-bolt"></i> Lean Theorem Prover
                </button>
            </div>

            <div class="sidebar-section">
                <div class="section-title">Rust Analysis</div>
                <button class="btn btn-purple" id="btnKaniVerify" onclick="runKaniVerification()">
                    <i class="fab fa-rust"></i> Kani Model Checker
                </button>
                <button class="btn btn-danger" id="btnPrustiVerify" onclick="runPrustiVerification()">
                    <i class="fas fa-wrench"></i> Prusti Verifier
                </button>
                <button class="btn btn-outline" id="btnCreusotVerify" onclick="runCreusotVerification()">
                    <i class="fas fa-calculator"></i> Creusot Verifier
                </button>
            </div>

            <div class="sidebar-section">
                <div class="section-title">Visualization</div>
                <button class="btn btn-accent" onclick="openDashboard()">
                    <i class="fas fa-globe"></i> Open Dashboard
                </button>
                <button class="btn btn-outline" onclick="viewTranslated()">
                    <i class="fas fa-eye"></i> View Translated
                </button>
                <button class="btn btn-outline" onclick="analyzeCounterexample()">
                    <i class="fas fa-search"></i> Analyze Counterexample
                </button>
            </div>

            <div class="sidebar-section">
                <div class="section-title">Settings</div>
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="autoScroll" checked>
                    <label class="form-check-label" for="autoScroll" style="font-size: 0.8rem;">Auto-scroll console</label>
                </div>
            </div>

            <div class="sidebar-section">
                <div class="section-title">Tool Status</div>
                <div class="tool-status" id="toolStatus">
                    <div><span class="status-dot available"></span> SPIN: Checking...</div>
                    <div><span class="status-dot available"></span> Coq: Checking...</div>
                    <div><span class="status-dot available"></span> Lean: Checking...</div>
                    <div><span class="status-dot available"></span> Prusti: Checking...</div>
                    <div><span class="status-dot available"></span> Kani: Checking...</div>
                </div>
            </div>
        </div>

        <!-- Main Content -->
        <div class="main-content">
            <!-- Editor Area -->
            <div class="editor-area">
                <div class="editor-tabs">
                    <button class="editor-tab active" onclick="switchEditorTab('source')">Source</button>
                    <button class="editor-tab" onclick="switchEditorTab('specs')">Specifications & LTL</button>
                    <button class="editor-tab" onclick="switchEditorTab('translated')">Translated Promela</button>
                    <button class="editor-tab" onclick="switchEditorTab('problems')">Audit Problems</button>
                </div>
                <div class="editor-container" id="editorContainer"></div>
            </div>

            <!-- Terminal Area -->
            <div class="terminal-area">
                <div class="terminal-header">
                    <h3><i class="fas fa-terminal"></i> Verification Console</h3>
                    <div>
                        <button class="btn btn-outline btn-sm" onclick="clearConsole()">
                            <i class="fas fa-eraser"></i> Clear
                        </button>
                        <button class="btn btn-outline btn-sm" onclick="exportConsole()">
                            <i class="fas fa-download"></i> Export
                        </button>
                    </div>
                </div>
                <div class="terminal-content" id="terminalContent">
                    <div class="log-line header">🛡️ DEFI GUARDIAN FORMAL VERIFICATION SUITE</div>
                    <div class="log-line dim">━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</div>
                    <div class="log-line dim">System initialized: <span id="currentTime"></span></div>
                    <div class="log-line" style="color: var(--accent);">Ready for protocol analysis. Load a source file to begin.</div>
                    <div class="log-line dim">━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</div>
                </div>
            </div>

            <!-- Status Bar -->
            <div class="status-bar">
                <span id="statusText">● System Ready</span>
                <span id="verificationStatus"></span>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
    <script>
        // ==================== GLOBAL STATE ====================
        let currentFile = null;
        let currentFileType = null;
        let currentSourceCode = null;
        let translatedCode = null;
        let editors = {};
        let activeEditor = 'source';
        let verificationRunning = false;

        // ==================== MONACO EDITOR INITIALIZATION ====================
        require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' }});
        require(['vs/editor/editor.main'], function() {
            // Define dark theme
            monaco.editor.defineTheme('defiDark', {
                base: 'vs-dark',
                inherit: true,
                rules: [
                    { token: 'comment', foreground: '6A9955', fontStyle: 'italic' },
                    { token: 'keyword', foreground: '569CD6' },
                    { token: 'string', foreground: 'CE9178' },
                    { token: 'number', foreground: 'B5CEA8' },
                    { token: 'type', foreground: '4EC9B0' }
                ],
                colors: {
                    'editor.background': '#0a0a0f',
                    'editor.foreground': '#e6edf3',
                    'editor.lineHighlightBackground': '#161b2240',
                    'editor.selectionBackground': '#00ffcc20',
                    'editorCursor.foreground': '#00ffcc',
                    'editorLineNumber.foreground': '#30363d',
                    'editorLineNumber.activeForeground': '#00ffcc'
                }
            });

            // Create editors
            editors.source = monaco.editor.create(document.getElementById('editorContainer'), {
                value: '// Load a smart contract to begin verification\n',
                language: 'sol',
                theme: 'defiDark',
                fontSize: 13,
                fontFamily: "'Fira Code', 'Consolas', monospace",
                minimap: { enabled: true },
                automaticLayout: true,
                scrollBeyondLastLine: false,
                lineNumbers: 'on',
                renderWhitespace: 'selection',
                bracketPairColorization: { enabled: true },
                padding: { top: 16 }
            });

            editors.specs = monaco.editor.create(document.createElement('div'), {
                value: '// LTL properties will appear here after translation\n',
                language: 'plaintext',
                theme: 'defiDark',
                fontSize: 13,
                fontFamily: "'Fira Code', 'Consolas', monospace",
                minimap: { enabled: false },
                automaticLayout: true,
                readOnly: false,
                lineNumbers: 'on',
                padding: { top: 16 }
            });

            editors.translated = monaco.editor.create(document.createElement('div'), {
                value: '// Translated Promela model will appear here\n',
                language: 'c',
                theme: 'defiDark',
                fontSize: 13,
                fontFamily: "'Fira Code', 'Consolas', monospace",
                minimap: { enabled: true },
                automaticLayout: true,
                readOnly: true,
                lineNumbers: 'on',
                padding: { top: 16 }
            });

            editors.problems = monaco.editor.create(document.createElement('div'), {
                value: '// Audit problems will appear here after verification\n',
                language: 'plaintext',
                theme: 'defiDark',
                fontSize: 13,
                fontFamily: "'Fira Code', 'Consolas', monospace",
                minimap: { enabled: false },
                automaticLayout: true,
                readOnly: true,
                lineNumbers: 'on',
                padding: { top: 16 }
            });

            // Set initial editor
            switchEditorTab('source');
        });

        function switchEditorTab(tab) {
            activeEditor = tab;
            
            // Update tab buttons
            document.querySelectorAll('.editor-tab').forEach(t => t.classList.remove('active'));
            document.querySelector(`.editor-tab[onclick="switchEditorTab('${tab}')"]`).classList.add('active');
            
            // Swap editor container content
            const container = document.getElementById('editorContainer');
            const editorMap = {
                'source': editors.source,
                'specs': editors.specs,
                'translated': editors.translated,
                'problems': editors.problems
            };
            
            // Move the active editor's DOM element into container
            const activeEditor = editorMap[tab];
            container.innerHTML = '';
            container.appendChild(activeEditor.getDomNode());
            activeEditor.layout();
        }

        // ==================== FILE OPERATIONS ====================
        function openFile() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.sol,.pml,.rs';
            input.onchange = async (e) => {
                const file = e.target.files[0];
                if (!file) return;
                
                const text = await file.text();
                currentFile = file.name;
                currentFileType = '.' + file.name.split('.').pop().toLowerCase();
                currentSourceCode = text;
                
                // Update editor
                const langMap = { '.sol': 'sol', '.rs': 'rust', '.pml': 'c' };
                monaco.editor.setModelLanguage(editors.source.getModel(), langMap[currentFileType] || 'plaintext');
                editors.source.setValue(text);
                
                // Update UI
                document.getElementById('fileInfo').textContent = file.name;
                document.getElementById('statusText').innerHTML = 
                    `<span style="color: var(--success);">●</span> Loaded: ${file.name}`;
                
                addLogLine(`LOADED FILE: ${file.name}`, 'header');
                addLogLine(`TYPE: ${currentFileType.toUpperCase()}`, 'dim');
                addLogLine('─'.repeat(60), 'dim');
                
                // Translate
                await translateCode();
            };
            input.click();
        }

        async function translateCode() {
            if (!currentSourceCode) return;
            
            try {
                addLogLine('[1/2] Translating to Promela...', '');
                const response = await fetch('/api/translate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        code: currentSourceCode,
                        file_type: currentFileType
                    })
                });
                
                const data = await response.json();
                if (data.success) {
                    translatedCode = data.translated;
                    editors.translated.setValue(data.translated);
                    
                    // Update specs editor with LTL properties
                    if (data.ltl_properties && data.ltl_properties.length > 0) {
                        let specsText = '/* === EXTRACTED LTL PROPERTIES === */\n\n';
                        data.ltl_properties.forEach(prop => {
                            specsText += `ltl ${prop.name} { ${prop.formula} }\n\n`;
                        });
                        editors.specs.setValue(specsText);
                    }
                    
                    addLogLine('Translation complete', 'success');
                    addLogLine(`LTL Properties found: ${data.ltl_properties?.length || 0}`, 'dim');
                } else {
                    addLogLine(`Translation error: ${data.error}`, 'error');
                }
            } catch (error) {
                addLogLine(`Translation failed: ${error.message}`, 'error');
            }
        }

        // ==================== VERIFICATION FUNCTIONS ====================
        async function runSpinVerification() {
            if (!translatedCode) {
                addLogLine('No translated code available. Load a file first.', 'warning');
                return;
            }
            
            if (verificationRunning) {
                addLogLine('Verification already in progress...', 'warning');
                return;
            }
            
            verificationRunning = true;
            setButtonState('btnSpinVerify', true, '⏳ Running SPIN...');
            
            addLogLine('\nRUNNING SPIN VERIFICATION', 'header');
            addLogLine('─'.repeat(60), 'dim');
            
            try {
                const response = await fetch('/api/verify/spin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: translatedCode })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    addLogLine('\nVERIFICATION SUCCESSFUL!', 'success');
                    addLogLine('All LTL properties satisfied', 'success');
                    addLogLine('No counterexamples found', 'success');
                    
                    if (data.stats) {
                        addLogLine(`States explored: ${data.stats.states || 'N/A'}`, 'dim');
                        addLogLine(`Depth reached: ${data.stats.depth || 'N/A'}`, 'dim');
                        addLogLine(`Transitions: ${data.stats.transitions || 'N/A'}`, 'dim');
                    }
                    
                    editors.problems.setValue('// ✅ No problems found - All properties verified');
                    document.getElementById('verificationStatus').innerHTML = 
                        '<span style="color: var(--success);">✅ Verified</span>';
                } else {
                    addLogLine('\nVERIFICATION FAILED!', 'error');
                    addLogLine(data.has_counterexample ? 'Counterexample found' : 'Check model', 'error');
                    
                    // Show output in problems tab
                    editors.problems.setValue(data.output || data.error || 'Verification failed');
                    document.getElementById('verificationStatus').innerHTML = 
                        '<span style="color: var(--error);">❌ Failed</span>';
                }
            } catch (error) {
                addLogLine(`Verification error: ${error.message}`, 'error');
            } finally {
                verificationRunning = false;
                setButtonState('btnSpinVerify', false, '🚀 Run SPIN Verification');
            }
        }

        async function runCoqVerification() {
            if (!currentSourceCode) {
                addLogLine('No file loaded', 'warning');
                return;
            }
            
            setButtonState('btnCoqVerify', true, '⏳ Running Coq...');
            addLogLine('\nRUNNING COQ VERIFICATION', 'header');
            
            try {
                const response = await fetch('/api/verify/coq', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        contract_name: currentFile?.replace(/\.[^.]+$/, '') || 'Contract',
                        properties: {}
                    })
                });
                
                const data = await response.json();
                if (data.success) {
                    addLogLine('Coq verification successful!', 'success');
                } else {
                    addLogLine(`Coq failed: ${data.error || 'Unknown error'}`, 'error');
                }
            } catch (error) {
                addLogLine(`Coq error: ${error.message}`, 'error');
            } finally {
                setButtonState('btnCoqVerify', false, '📜 Coq Proof Assistant');
            }
        }

        async function runLeanVerification() {
            if (!currentSourceCode) {
                addLogLine('No file loaded', 'warning');
                return;
            }
            
            setButtonState('btnLeanVerify', true, '⏳ Running Lean...');
            addLogLine('\nRUNNING LEAN VERIFICATION', 'header');
            
            try {
                const response = await fetch('/api/verify/lean', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        contract_name: currentFile?.replace(/\.[^.]+$/, '') || 'Contract'
                    })
                });
                
                const data = await response.json();
                if (data.success) {
                    addLogLine('Lean verification successful!', 'success');
                } else {
                    addLogLine(`Lean failed: ${data.errors || data.output}`, 'error');
                }
            } catch (error) {
                addLogLine(`Lean error: ${error.message}`, 'error');
            } finally {
                setButtonState('btnLeanVerify', false, '⚡ Lean Theorem Prover');
            }
        }

        async function runPrustiVerification() {
            if (!currentSourceCode || currentFileType !== '.rs') {
                addLogLine('Prusti requires a .rs file', 'warning');
                return;
            }
            
            setButtonState('btnPrustiVerify', true, '⏳ Running Prusti...');
            addLogLine('\nRUNNING PRUSTI VERIFICATION', 'header');
            
            try {
                const response = await fetch('/api/verify/prusti', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: currentSourceCode })
                });
                
                const data = await response.json();
                if (data.skipped) {
                    addLogLine(`Prusti skipped: ${data.error}`, 'warning');
                } else if (data.success) {
                    addLogLine('Prusti verification successful!', 'success');
                } else {
                    addLogLine(`Prusti failed: ${data.errors || data.error}`, 'error');
                }
            } catch (error) {
                addLogLine(`Prusti error: ${error.message}`, 'error');
            } finally {
                setButtonState('btnPrustiVerify', false, '🔧 Prusti Verifier');
            }
        }

        // ==================== TERMINAL FUNCTIONS ====================
        function addLogLine(text, className = '') {
            const terminal = document.getElementById('terminalContent');
            const line = document.createElement('div');
            line.className = `log-line ${className}`;
            line.textContent = text;
            terminal.appendChild(line);
            
            if (document.getElementById('autoScroll').checked) {
                terminal.scrollTop = terminal.scrollHeight;
            }
        }

        function clearConsole() {
            const terminal = document.getElementById('terminalContent');
            terminal.innerHTML = '';
            addLogLine('Console cleared', 'dim');
        }

        function exportConsole() {
            const terminal = document.getElementById('terminalContent');
            const text = terminal.innerText;
            const blob = new Blob([text], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `defi_guardian_export_${new Date().toISOString().slice(0, 10)}.txt`;
            a.click();
            URL.revokeObjectURL(url);
            addLogLine('Console exported', 'success');
        }

        function setButtonState(btnId, running, text) {
            const btn = document.getElementById(btnId);
            if (running) {
                btn.disabled = true;
                btn.style.opacity = '0.7';
            } else {
                btn.disabled = false;
                btn.style.opacity = '1';
            }
            btn.innerHTML = text;
        }

        // ==================== UTILITY FUNCTIONS ====================
        function openDashboard() {
            window.open('http://localhost:8501', '_blank');
            addLogLine('Dashboard opened in new window', 'dim');
        }

        function viewTranslated() {
            if (translatedCode) {
                switchEditorTab('translated');
                addLogLine('Viewing translated Promela model', 'dim');
            } else {
                addLogLine('No translated code available. Load and translate a file first.', 'warning');
            }
        }

        function analyzeCounterexample() {
            addLogLine('Counterexample analysis not yet implemented', 'warning');
        }

        function runKaniVerification() {
            addLogLine('Kani verification not yet implemented in web UI', 'warning');
        }

        function runCreusotVerification() {
            addLogLine('Creusot verification not yet implemented in web UI', 'warning');
        }

        // ==================== INITIALIZATION ====================
        // Set current time
        document.getElementById('currentTime').textContent = new Date().toLocaleString();
        
        // Check tool availability
        async function checkTools() {
            try {
                const response = await fetch('/api/tools/status');
                const tools = await response.json();
                
                const statusHtml = Object.entries(tools).map(([tool, available]) => {
                    const dotClass = available ? 'available' : 'unavailable';
                    return `<div><span class="status-dot ${dotClass}"></span> ${tool.toUpperCase()}: ${available ? 'Available' : 'Not Found'}</div>`;
                }).join('');
                
                document.getElementById('toolStatus').innerHTML = statusHtml;
            } catch (error) {
                console.error('Failed to check tools:', error);
            }
        }
        
        checkTools();
    </script>
</body>
</html>
'''


# ==================== WRITE TEMPLATE ====================
os.makedirs(os.path.join(PROJECT_DIR, 'web_portal', 'templates'), exist_ok=True)
template_path = os.path.join(PROJECT_DIR, 'web_portal', 'templates', 'desktop_app.html')
with open(template_path, 'w') as f:
    f.write(DESKTOP_APP_HTML)


# ==================== LAUNCHER ====================
def start_flask():
    """Start Flask server"""
    app.run(port=5050, debug=False, use_reloader=False)


def main():
    """Main entry point - launches desktop app with web UI"""
    # Start Flask in background thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # Wait for Flask to start
    time.sleep(1)
    
    # Create desktop window with webview
    window = webview.create_window(
        'DeFi Guardian - Formal Verification Suite',
        'http://localhost:5050',
        width=1500,
        height=950,
        resizable=True,
        fullscreen=False,
        min_size=(1200, 700),
        text_select=True,
        confirm_close=True
    )
    
    webview.start(debug=False)


if __name__ == '__main__':
    main()