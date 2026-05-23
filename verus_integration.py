# verus_integration.py
import subprocess

class VerusIntegration:
    """Integrates Verus SMT-based verifier for Rust"""
    
    def __init__(self):
        self.verus_available = self._check_verus()
    
    def _check_verus(self):
        try:
            subprocess.run(["verus", "--version"], capture_output=True)
            return True
        except:
            return False
    
    def annotate_for_verus(self, rust_code: str) -> str:
        """
        Add Verus specifications to Rust code.
        Verus uses spec functions, requires/ensures, and proof blocks.
        """
        # Check if already has Verus macro
        if "verus!" in rust_code:
            return rust_code
        
        # Add Verus prelude
        header = """use vstd::prelude::*;

verus! {
"""
        footer = """
} // verus!
"""
        
        # Add specifications to functions
        import re
        
        def add_specs(match):
            func_sig = match.group(0)
            func_name = match.group(1)
            
            # Generate appropriate specs based on function name
            specs = []
            if "deposit" in func_name:
                specs.append("#[verus::spec]")
                specs.append("requires(amount > 0);")
                specs.append("ensures(self.balance == old(self.balance) + amount);")
            elif "withdraw" in func_name:
                specs.append("#[verus::spec]")
                specs.append("requires(amount <= self.balance);")
                specs.append("ensures(self.balance == old(self.balance) - amount);")
            
            return "\n    ".join(specs) + "\n    " + func_sig if specs else func_sig
        
        # Apply to function definitions
        annotated = re.sub(
            r'pub\s+fn\s+(\w+)\s*\([^)]*\)[^{]*\{',
            add_specs,
            rust_code
        )
        
        return header + annotated + footer
    
    def verify_with_verus(self, rust_file: str) -> dict:
        """Run Verus verification"""
        result = subprocess.run(
            ["verus", rust_file],
            capture_output=True, text=True,
            timeout=300
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "errors": result.stderr
        }