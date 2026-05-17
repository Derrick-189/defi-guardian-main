"""Certora Prover trace parser."""

import re
import os
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep
from trace_parsers import TraceParser


class CertoraParser(TraceParser):
    """Parser for Certora Prover output"""

    def parse_rules(self, log_path: str) -> List[Dict]:
        """Extract rules from Certora output"""
        if not log_path or not os.path.exists(log_path):
            return []

        rules = []
        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        # Pattern: "Rule name ... PASS/FAIL/TIMEOUT"
        rule_pattern = re.compile(r"Rule\s+(\w+).*?(PASS|FAIL|TIMEOUT|ERROR)", re.IGNORECASE)

        for match in rule_pattern.finditer(content):
            rule_name = match.group(1)
            result = match.group(2).upper()

            rules.append(
                {
                    "name": rule_name,
                    "status": result,
                    "formula": f"rule {rule_name}",
                    "errors": 0 if result == "PASS" else 1,
                    "tool_specific": {"result": result},
                }
            )

        if not rules:
            if "FAILED" in content or "failed" in content:
                rules.append(
                    {
                        "name": "Certora Verification",
                        "status": "FAIL",
                        "formula": "Certora prover",
                        "errors": 1,
                        "tool_specific": {},
                    }
                )
            else:
                rules.append(
                    {
                        "name": "Certora Verification",
                        "status": "PASS",
                        "formula": "Certora prover",
                        "errors": 0,
                        "tool_specific": {},
                    }
                )

        return rules

    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """Extract Certora counterexample as trace"""
        trace = ExecutionTrace()

        if not log_path or not os.path.exists(log_path):
            return trace

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return trace

        # Extract violation lines
        for i, line in enumerate(content.splitlines()):
            if (
                "violation" in line.lower()
                or "error" in line.lower()
                or "assert" in line.lower()
            ):
                step = TraceStep(
                    step_num=i + 1,
                    proc="Certora",
                    action=line.strip(),
                    state="violation",
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
                "Check solc version matches contract pragma (solc8.17 vs pragma solidity)",
                "Ensure envfree functions truly do not read msg.sender",
                "Verify method signatures in the methods block match the contract ABI",
                "Check CERTORAKEY environment variable is set",
            ]
        return ["Certora verification passed - rules verified"]
