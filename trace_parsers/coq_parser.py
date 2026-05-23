"""Coq proof assistant trace parser."""

import re
import os
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep
from trace_parsers import TraceParser


class CoqParser(TraceParser):
    """Parser for Coq verification output"""

    def parse_rules(self, log_path: str) -> List[Dict]:
        """Extract theorems and their proof status from Coq log"""
        if not log_path or not os.path.exists(log_path):
            return []

        rules = []
        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        # Patterns for theorem/lemma definitions
        thm_pattern = re.compile(r"^(Theorem|Lemma)\s+(\w+)", re.MULTILINE | re.IGNORECASE)
        qed_pattern = re.compile(r"\bQed\b|\bDefined\b")
        adm_pattern = re.compile(r"\bAdmitted\b|Error:", re.IGNORECASE)

        current_thm = None
        for line in content.splitlines():
            thm_match = thm_pattern.search(line)
            if thm_match:
                current_thm = thm_match.group(2)
                continue

            if current_thm:
                if qed_pattern.search(line):
                    rules.append(
                        {
                            "name": current_thm,
                            "status": "PASS",
                            "formula": f"Theorem {current_thm}",
                            "errors": 0,
                            "tool_specific": {"proof_status": "Qed"},
                        }
                    )
                    current_thm = None
                elif adm_pattern.search(line):
                    rules.append(
                        {
                            "name": current_thm,
                            "status": "FAIL",
                            "formula": f"Theorem {current_thm}",
                            "errors": 1,
                            "tool_specific": {"proof_status": "Admitted"},
                        }
                    )
                    current_thm = None

        if not rules:
            if "Error" in content or "error" in content:
                rules.append(
                    {
                        "name": "Coq Verification",
                        "status": "FAIL",
                        "formula": "Coq proof assistant",
                        "errors": 1,
                        "tool_specific": {},
                    }
                )
            else:
                rules.append(
                    {
                        "name": "Coq Verification",
                        "status": "PASS",
                        "formula": "Coq proof assistant",
                        "errors": 0,
                        "tool_specific": {},
                    }
                )

        return rules

    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """Extract Coq error messages as structured trace steps with file/line."""
        trace = ExecutionTrace()

        if not log_path or not os.path.exists(log_path):
            return trace

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return trace

        lines = content.splitlines()
        i = 0
        step_counter = 1

        while i < len(lines):
            line = lines[i]
            # Coq error blocks start with "File " line
            if line.startswith("File "):
                # Extract file and line number
                m = re.search(r'File "([^"]+)", line (\d+)', line)
                if not m:
                    i += 1
                    continue
                file = m.group(1)
                line_num = m.group(2)

                # Collect subsequent non-empty lines until a new "File " or blank line
                i += 1
                error_lines = []
                while i < len(lines):
                    l = lines[i].strip()
                    if l == "" or lines[i].startswith("File "):
                        break
                    error_lines.append(l)
                    i += 1

                action = " ".join(error_lines).strip()

                # Only keep blocks that look like errors (contain "Error" or "failed")
                if not any(kw in action.lower() for kw in ("error", "failed")):
                    # Not an error block, skip
                    continue

                step = TraceStep(
                    step_num=step_counter,
                    proc="Coq",
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
                # note: i already at next block start or after block
                continue
            else:
                i += 1

        # Set final state from last step if available
        if trace.steps:
            last = trace.steps[-1]
            trace.final_state = last.state
            trace.final_variables = last.variables

        return trace

    def get_recommendations(self, status: str) -> List[str]:
        """Coq-specific recommendations"""
        if status == "FAIL":
            return [
                "Check that all Prop definitions are well-typed",
                "Replace admit/Admitted with concrete proof tactics (lia, omega, auto)",
                "Ensure bool fields use = true / = false comparisons, not >= 0",
                "Use native_decide for decidable propositions",
            ]
        return ["Proof verified successfully"]
