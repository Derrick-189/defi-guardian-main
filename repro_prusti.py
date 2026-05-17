
import os
import sys
from rust_verifiers import RustVerifier

def main():
    verifier = RustVerifier()
    code = """
pub fn add(a: u32, b: u32) -> u32 {
    a + b
}
"""
    print("Running Prusti...")
    result = verifier.verify_with_prusti(code)
    print(f"Success: {result['success']}")
    print(f"Error: {result['error']}")
    print(f"Failure Kind: {result.get('failure_kind')}")
    print(f"Failure Hint: {result.get('failure_hint')}")
    if not result['success']:
        print("--- STDERR ---")
        print(result['errors'])

if __name__ == "__main__":
    main()
