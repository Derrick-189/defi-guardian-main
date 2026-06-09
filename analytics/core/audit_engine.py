import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any

class ProfessionalAuditEngine:
    """
    Advanced auditing engine for formal verification results.
    Tracks deep metrics required for professional security audits.
    """
    
    def __init__(self, verification_results: Dict[str, Any]):
        self.results = verification_results
        self.timestamp = datetime.utcnow()
        self.risk_score = 0.0
        
    def calculate_state_coverage(self) -> Dict[str, float]:
        """Calculates state space exploration completeness."""
        explored = self.results.get('states_explored', 0)
        estimated_total = self.results.get('estimated_state_space', 1)
        # Avoid division by zero
        estimated_total = max(1, estimated_total)
        coverage_pct = min(100.0, (explored / estimated_total) * 100)
        
        return {
            "explored_states": explored,
            "coverage_percentage": round(coverage_pct, 2),
            "is_exhaustive": coverage_pct >= 99.9
        }
        
    def analyze_invariant_violations(self) -> List[Dict[str, Any]]:
        """Classifies invariant violations by severity (Critical, High, Medium, Low)."""
        violations = self.results.get('violations', [])
        classified = []
        
        for v in violations:
            severity = "Low"
            vtype = v.get('type', '').lower()
            if "reentrancy" in vtype:
                severity = "Critical"
                self.risk_score += 35.0
            elif "overflow" in vtype or "underflow" in vtype:
                severity = "High"
                self.risk_score += 20.0
            elif "access_control" in vtype:
                severity = "Critical"
                self.risk_score += 30.0
            else:
                self.risk_score += 5.0
                
            classified.append({
                "property": v.get('property', 'Unknown'),
                "severity": severity,
                "trace_length": v.get('depth', 0),
                "description": v.get('description', 'Invariant violation detected')
            })
            
        return sorted(classified, key=lambda x: {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}[x['severity']], reverse=True)

    def generate_audit_summary(self) -> Dict[str, Any]:
        """Generates a high-level executive summary of the audit."""
        coverage = self.calculate_state_coverage()
        violations = self.analyze_invariant_violations()
        
        # Normalize risk score (0-100)
        final_score = max(0.0, 100.0 - self.risk_score)
        
        audit_grade = "A"
        if final_score < 90: audit_grade = "B"
        if final_score < 70: audit_grade = "C"
        if final_score < 50: audit_grade = "D"
        if final_score < 30: audit_grade = "F"
        
        return {
            "timestamp": self.timestamp.isoformat(),
            "security_score": final_score,
            "audit_grade": audit_grade,
            "coverage": coverage,
            "critical_issues": sum(1 for v in violations if v['severity'] == "Critical"),
            "high_issues": sum(1 for v in violations if v['severity'] == "High"),
            "is_safe_to_deploy": final_score >= 90 and len(violations) == 0
        }
