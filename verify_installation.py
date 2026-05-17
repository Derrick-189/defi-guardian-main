#!/usr/bin/env python3
"""
verify_installation.py - Check that all DeFi Guardian components work
"""

import subprocess
import sys
import os

def check_tool(name, cmd, expected_output=None):
    """Check if a tool is installed and working"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            if expected_output and expected_output not in result.stdout + result.stderr:
                return False, f"Unexpected output"
            return True, result.stdout.split('\n')[0][:60]
        return False, result.stderr[:60]
    except Exception as e:
        return False, str(e)[:60]

def main():
    print("=" * 60)
    print("DeFi Guardian - Installation Verification")
    print("=" * 60)
    print()
    
    tools = {
        "SPIN": "spin -V 2>&1",
        "Coq": "coqc --version 2>&1",
        "Lean": "lean --version 2>&1",
        "Rust": "rustc --version",
        "Cargo": "cargo --version",
        "Z3": "z3 --version",
        "Python": "python3 --version",
        "Graphviz": "dot -V 2>&1",
    }
    
    all_ok = True
    
    for name, cmd in tools.items():
        ok, msg = check_tool(name, cmd)
        if ok:
            print(f"✅ {name:12} {msg}")
        else:
            print(f"❌ {name:12} {msg}")
            all_ok = False
    
    print()
    print("=" * 60)
    
    # Check Python imports
    print("\nChecking Python dependencies...")
    deps = ["customtkinter", "streamlit", "plotly", "pandas", "numpy", "PIL", "graphviz", "networkx"]
    
    for dep in deps:
        try:
            __import__(dep)
            print(f"✅ {dep}")
        except ImportError:
            print(f"❌ {dep} - run: pip install {dep}")
            all_ok = False
    
    print()
    print("=" * 60)
    
    if all_ok:
        print("\n✅ All checks passed! DeFi Guardian is ready to use.")
    else:
        print("\n⚠️ Some components are missing. Please review the errors above.")
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())