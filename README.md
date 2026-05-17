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
# defi-guardian-main
