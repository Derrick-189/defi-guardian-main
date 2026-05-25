# DeFi Guardian User Guide 
 
 ## Quick Start 
 
 1. Launch DeFi Guardian: `python launcher.py` 
 2. Click "Open Source File" and select your smart contract 
 3. Click "Run SPIN Verification" 
 4. View results in dashboard at http://localhost:8501 
 
 ## Supported Files 
 
 - `.sol` - Solidity contracts (auto-translated) 
 - `.rs` - Rust programs (experimental) 
 - `.pml` - Promela models (direct verification) 
 
 ## Interpreting Results 
 
 - ✅ PASS: All properties verified 
 - ❌ FAIL: Counterexample found (review trail file) 
 - ⏭️ SKIP: Tool not applicable to this file

 ## System dependencies (Linux / Debian/Ubuntu)

The project requires some system packages to build Python native extensions (notably `psycopg2`). Run the helper script as root on Debian/Ubuntu systems:

```bash
sudo ./scripts/install_system_deps.sh
```

If that fails, use the shell interpreter directly:

```bash
sudo bash ./scripts/install_system_deps.sh
```

Then activate the virtualenv and install Python requirements:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

If you prefer the raw commands, run:

```bash
sudo apt-get update
sudo apt-get install -y build-essential libpq-dev python3-dev pkg-config
source .venv/bin/activate
pip install -r requirements.txt
```
# defi-guardian-main
# defi-guardian-main
# defi-guardian-main
