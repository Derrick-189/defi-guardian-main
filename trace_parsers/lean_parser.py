"""Lean 4 theorem prover trace parser."""

import re
import os
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep
from trace_parsers import TraceParser


class LeanParser(TraceParser):
    """Parser for Lean 4 verification output"""

    def parse_rules(self, log_path: str) -> List[Dict]:
        """Extract theorems from Lean log"""
        if not log_path or not os.path.exists(log_path):
            return []

        rules = []
        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        # Patterns for theorems
        thm_pattern = re.compile(
            r"^(theorem|lemma|def|#check)\s+(\w+)", re.MULTILINE | re.IGNORECASE
        )
        has_error = "error" in content.lower() or "failed" in content.lower()

        current_thm = None
        for line in content.splitlines():
            m = thm_pattern.search(line)
            if m:
                current_thm = m.group(2)
                rules.append(
                    {
                        "name": current_thm,
                        "status": "FAIL" if has_error else "PASS",
                        "formula": line.strip(),
                        "errors": 1 if has_error else 0,
                        "tool_specific": {"kind": m.group(1)},
                    }
                )

        if not rules:
            rules.append(
                {
                    "name": "Lean Verification",
                    "status": "FAIL" if has_error else "PASS",
                    "formula": "Lean theorem proving",
                    "errors": 1 if has_error else 0,
                    "tool_specific": {},
                }
            )

        return rules

    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """Extract Lean error messages with file:line:col information."""
        trace = ExecutionTrace()

        if not log_path or not os.path.exists(log_path):
            return trace

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return trace

        step_counter = 1
        for i, line in enumerate(content.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            # Check if line indicates an error
            if "error" in stripped.lower() or "failed" in stripped.lower():
                # Try to extract file:line:col pattern
                file = ""
                line_num = str(i)
                m = re.match(r'^(.+?):(\d+):(\d+):', stripped)
                if m:
                    file = m.group(1)
                    line_num = m.group(2)
                    # action text after the colon-colon
                    action = stripped[m.end():].strip()
                else:
                    action = stripped

                step = TraceStep(
                    step_num=step_counter,
                    proc="Lean",
                    action=action,
                    state="error",
                    line=line_num,
                    file=file,
                    variables={},
                    updates={},
                    is_error=True,
                )
                trace.steps.append(step)
                if step_counter == 1:
                    trace.error_line = step_counter
                    trace.error_message = action
                step_counter += 1

        # Set final state from last step if available
        if trace.steps:
            last = trace.steps[-1]
            trace.final_state = last.state
            trace.final_variables = last.variables

        return trace

    def get_recommendations(self, status: str) -> List[str]:
        if status == "FAIL":
            return [
                "Check theorem statement types match (Nat vs Int)",
                "Use decide or native_decide for decidable goals",
                "Ensure all imports are available",
            ]
        return ["Lean theorem verified successfully"]
