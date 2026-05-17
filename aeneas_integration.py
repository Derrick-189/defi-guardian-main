# aeneas_integration.py
import subprocess
import json
import os

class AeneasTranslator:
    """Integrates CHARON/AENEAS pipeline for Rust-to-Coq/Lean translation"""
    
    def __init__(self):
        self.charon_available = self._check_charon()
        self.aeneas_available = self._check_aeneas()
    
    def _check_charon(self):
        try:
            subprocess.run(["charon", "--version"], capture_output=True)
            return True
        except:
            return False
    
    def _check_aeneas(self):
        try:
            subprocess.run(["aeneas", "--version"], capture_output=True)
            return True
        except:
            return False
    
    def translate_rust_to_coq(self, rust_file: str) -> dict:
        """
        Use CHARON to extract LLBC, then AENEAS to generate Coq.
        This is the REAL translation pipeline, not a template!
        """
        # Step 1: Extract LLBC using CHARON
        charon_result = subprocess.run(
            ["charon", "extract", "--input", rust_file, "--output", "output.llbc"],
            capture_output=True, text=True
        )
        
        if charon_result.returncode != 0:
            return {"success": False, "error": f"CHARON failed: {charon_result.stderr}"}
        
        # Step 2: Translate LLBC to Coq using AENEAS
        aeneas_result = subprocess.run(
            ["aeneas", "-backend", "coq", "output.llbc", "-o", "output.v"],
            capture_output=True, text=True
        )
        
        if aeneas_result.returncode != 0:
            return {"success": False, "error": f"AENEAS failed: {aeneas_result.stderr}"}
        
        # Step 3: Read generated Coq file
        with open("output.v", "r") as f:
            coq_code = f.read()
        
        return {
            "success": True,
            "coq_code": coq_code,
            "functions_translated": self._count_translated_functions(coq_code)
        }
    
    def _count_translated_functions(self, coq_code: str) -> int:
        """Count how many Rust functions were successfully translated"""
        import re
        return len(re.findall(r'Definition\s+\w+\s*\(', coq_code))