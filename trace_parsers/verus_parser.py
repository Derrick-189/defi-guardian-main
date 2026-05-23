"""Verus verification tool trace parser."""

import re
import os
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep
from trace_parsers import TraceParser


class VerusParser(TraceParser):
    """Parser for Verus specification language output"""

    def parse_rules(self, log_path: str) -> List[Dict]:
        """Extract verification results from Verus output"""
        if not log_path or not os.path.exists(log_path):
            return []

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        rules = []

        # Look for proof results in verus! blocks
        proof_pattern = re.compile(
            r"proof\s+(\w+)\s*.*?(verified|failed|timeout)", re.IGNORECASE | re.DOTALL
        )

        for match in proof_pattern.finditer(content):
            proof_name = match.group(1)
            result = match.group(2).lower()

            status_map = {
                "verified": "PASS",
                "failed": "FAIL",
                "timeout": "TIMEOUT",
            }

            rules.append(
                {
                    "name": proof_name,
                    "status": status_map.get(result, "FAIL"),
                    "formula": f"proof {proof_name}",
                    "errors": 0 if result == "verified" else 1,
                    "tool_specific": {"proof_type": "verus_proof"},
                }
            )

        if not rules:
            has_error = "error" in content.lower() or "failed" in content.lower()
            rules.append(
                {
                    "name": "Verus Verification",
                    "status": "FAIL" if has_error else "PASS",
                    "formula": "Verus SMT verification",
                    "errors": 1 if has_error else 0,
                    "tool_specific": {},
                }
            )

        return rules

    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """Extract error messages as trace"""
        trace = ExecutionTrace()

        if not log_path or not os.path.exists(log_path):
            return trace

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return trace

        # Extract error/failure lines
        for i, line in enumerate(content.splitlines()):
            if (
                "error" in line.lower()
                or "failed" in line.lower()
                or "assertion" in line.lower()
                or "timeout" in line.lower()
            ):
                step = TraceStep(
                    step_num=i + 1,
                    proc="Verus",
                    action=line.strip(),
                    state="error",
                    line=str(i),
                    file="",
                    is_error=True,
                )
                trace.steps.append(step)
                trace.error_line = i + 1
                trace.error_message = line.strip()

        return trace

    def get_recommendations(self, status: str) -> List[str]:
        if status == "FAIL":
            return [
                "Review the SMT solver counterexample",
                "Check assertion conditions in verus! blocks",
                "Verify loop invariants cover all state changes",
                "Consider adding intermediate lemmas to help SMT solver",
            ]
        elif status == "TIMEOUT":
            return [
                "Simplify complex assertions",
                "Add intermediate proof steps to guide SMT solver",
                "Consider using assert and assume strategically",
            ]
        return ["Verus verification successful - all proofs verified"]
