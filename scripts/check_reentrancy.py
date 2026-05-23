#!/usr/bin/env python3
"""
Pre-commit hook: Check for reentrancy patterns in Solidity
"""

import sys
import re


def check_reentrancy(filepath):
    """Check Solidity file for reentrancy vulnerabilities"""
    with open(filepath, 'r') as f:
        code = f.read()
    
    issues = []
    
    # Check for external calls before state updates
    external_call_pattern = r'\.call\{.*?\}'
    state_update_pattern = r'(\w+)\s*=\s*[^;]+;'
    
    lines = code.split('\n')
    external_call_line = -1
    
    for i, line in enumerate(lines):
        if re.search(external_call_pattern, line):
            external_call_line = i
        
        # Check if state update comes after external call in same function
        if external_call_line >= 0 and re.search(state_update_pattern, line):
            if i > external_call_line:
                issues.append({
                    'line': i + 1,
                    'issue': 'State update after external call (potential reentrancy)',
                    'suggestion': 'Move state update before external call or use ReentrancyGuard'
                })
    
    # Check for missing nonReentrant modifier
    if 'nonReentrant' not in code and '.call' in code:
        issues.append({
            'line': 1,
            'issue': 'External calls detected without nonReentrant modifier',
            'suggestion': 'Add OpenZeppelin ReentrancyGuard and nonReentrant modifier'
        })
    
    return issues


def main():
    if len(sys.argv) < 2:
        return 0
    
    all_passed = True
    for filepath in sys.argv[1:]:
        if filepath.endswith('.sol'):
            print(f"\n🔍 Checking reentrancy: {filepath}")
            issues = check_reentrancy(filepath)
            
            if issues:
                all_passed = False
                for issue in issues:
                    print(f"  ❌ Line {issue['line']}: {issue['issue']}")
                    print(f"     💡 {issue['suggestion']}")
            else:
                print(f"  ✅ No reentrancy issues detected")
    
    if not all_passed:
        print("\n❌ Reentrancy check failed!")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
