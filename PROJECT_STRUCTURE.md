# DeFi Guardian Project Structure

This document describes the directory layout, core files, and the data pipeline for formal verification results within the DeFi Guardian project.

## Directory Structure

| Directory | Description |
|-----------|-------------|
| `web_portal/` | Main Flask web application directory. |
| `web_portal/templates/` | Jinja2 HTML templates for the web portal UI. |
| `generated/` | Root for all files generated during verification (models, reports, images). |
| `models/` | Contains translated formal models (e.g., `.pml` for SPIN). |
| `logs/` | Organized logs for different tools (`spin/`, `certora/`, `coq/`, `lean/`, `rust_tools/`). |
| `certora/` | Certora-specific workspace containing contracts, specs, and configurations. |
| `benchmarks/` | Performance benchmark results for various verification tasks. |
| `console_exports/` | Exported terminal outputs from the Desktop App. |
| `scripts/` | Helper utility scripts. |

## Core System Files

| File | Role |
|------|------|
| `desktop_app.py` | The main IDE-like Desktop Application. It coordinates tool execution and provides the primary UI. |
| `app.py` (root) | A high-performance Streamlit dashboard for real-time verification visualization. |
| `web_portal/app.py` | The backend for the Web Portal. It manages user accounts, audit history, and provides APIs for the UI. |
| `translator.py` | Responsible for translating Solidity and Rust source code into Promela models. |
| `rust_verifiers.py` | Implements verification logic for Rust tools like Kani, Prusti, and Creusot. |
| `coq_verifier.py` | Handles Coq script generation and proof execution. |
| `lean_verifier.py` | Manages Lean 4 verification and theorem proving. |
| `counterexample_analyzer.py` | Parses SPIN trail files to generate structured execution traces for visualization. |

---

## Formal Verification Results Pipeline

The following diagram-like flow describes how results move from the verification tools to your dashboards:

### 1. Execution & Capture
Verification is usually triggered from the **Desktop App** (`desktop_app.py`).
- Methods like `save_verification_state` and `log_job_history` capture the raw output from tools (SPIN, Certora, Kani, etc.).

### 2. Data Persistence (Sources of Truth)
Results are written to several local data stores:
- **`verification_state.json`**: Stores the status, success/fail, and raw output of the *latest* run for every tool.
- **`generated/reports/audit_log.json`**: A JSON-based historical log of all verification jobs performed on the desktop.
- **`web_portal/defi_guardian.db`**: An SQLite database where `desktop_app.py` mirrors its job history via the `save_portal_audit_record` method.

### 3. Dashboard Integration
Dashboards consume the stored data in two ways:

#### **Streamlit Dashboard (port 5005)**
- Directly reads `verification_state.json` using the `load_verification_state()` function in the root `app.py`.
- It monitors this file for changes to provide real-time updates.

#### **Web Portal Dashboard (port 5000)**
- The **Backend** (`web_portal/app.py`) serves the data via several API endpoints:
    - `/api/state/current`: Returns the content of `verification_state.json`.
    - `/api/desktop-runs`: Returns historical data from `audit_log.json`.
    - `/api/counterexample/<id>` & `/api/trace/<id>`: Serve detailed trace data for visual analysis.
- The **Frontend** templates (`dashboard.html`, `counterexample.html`) perform `fetch()` calls to these endpoints to populate the UI.

## Web Portal Templates Overview

| Template | Description |
|----------|-------------|
| `base.html` | The master layout containing common CSS (Bootstrap), JS, and navigation. |
| `index.html` | Landing page for unauthenticated users. |
| `dashboard.html` | User's main cockpit showing personal audit history and desktop sync data. |
| `counterexample.html` | The redesigned Certora-style analysis tool (three-panel layout). |
| `trace.html` | Dedicated execution trace viewer. |
| `visualization.html` | 3D state space graph explorer (Three.js). |
| `desktop_app.html` | A specialized template for the Desktop App's embedded web components. |

## System Rebuild & Startup Guide

To rebuild or run the complete DeFi Guardian system, follow these steps:

### 1. Environment Setup
- Install Python dependencies: `pip install -r requirements.txt`.
- Install verification tools: `spin`, `coqc`, `lean`, `slither`, etc. (See `install.sh`).

### 2. Launching the Components
The system consists of three main integrated services:

- **Desktop IDE**: `python desktop_app.py`
  - *Provides*: Main tool coordination, code editing, and background job execution.
- **Web Portal (API/User DB)**: `python web_portal/app.py` (Default: port 5000)
  - *Provides*: User auth, persistence for all results, and the primary high-end UI.
- **Streamlit Dashboard**: `streamlit run app.py` (Default: port 5005)
  - *Provides*: Real-time state-space visualization and risk monitoring.

### 3. Data Flow Integrity
To ensure the system works as a whole:
- The **Desktop IDE** must be able to write to the root `verification_state.json`.
- The **Web Portal** must have read access to `audit_log.json` and the shared SQLite database `web_portal/defi_guardian.db`.
