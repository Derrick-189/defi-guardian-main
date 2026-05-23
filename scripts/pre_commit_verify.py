#!/usr/bin/env python3
"""
Pre-commit hook for DeFi Guardian
Validates that smart contracts generate proper LTL properties
"""

import sys
import os
import re

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translator import DeFiTranslator

REQUIRED_LTL_PATTERNS = {
    'safety': r'ltl\s+safety.*\{',
    'liveness': r'ltl\s+liveness.*\{',
    'invariant': r'ltl\s+invariant.*\{',
}


def verify_file(filepath):
    """Check if a file generates valid LTL properties"""
    print(f"\n🔍 Checking: {filepath}")
    
    with open(filepath, 'r') as f:
        code = f.read()
    
    # Translate based on extension
    if filepath.endswith('.sol'):
        pml = DeFiTranslator.translate_solidity(code)
    elif filepath.endswith('.rs'):
        pml = DeFiTranslator.translate_rust(code)
    else:
        print(f"  ⏭️ Skipping unsupported file: {filepath}")
        return True
    
    # Check for required LTL patterns
    all_found = True
    for pattern_name, pattern in REQUIRED_LTL_PATTERNS.items():
        if re.search(pattern, pml):
            print(f"  ✅ Found {pattern_name} property")
        else:
            print(f"  ❌ Missing {pattern_name} property")
            all_found = False
    
    return all_found


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("No files to check")
        return 0
    
    all_passed = True
    for filepath in sys.argv[1:]:
        if filepath.endswith(('.sol', '.rs')):
            if not verify_file(filepath):
                all_passed = False
    
    if not all_passed:
        print("\n❌ Pre-commit check failed: Missing required LTL properties")
        print("   Please ensure your contract includes proper safety specifications.")
        return 1
    
    print("\n✅ All pre-commit checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
