"""
SPIN Model Checker trace parser.
Parses LTL properties and SPIN trail files into normalized format.
"""

import re
import os
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep, LTLProperty
from trace_parsers import TraceParser


class SPINParser(TraceParser):
    """Parser for SPIN verification output and trail files"""

    def parse_rules(self, log_path: str) -> List[Dict]:
        """
        Extract LTL properties from SPIN log file.
        Format: "--- LTL property_name ---" followed by "errors: N"
        """
        if not log_path or not os.path.exists(log_path):
            return []

        rules = []
        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        # Pattern: "--- LTL property_name ---" + "errors: N"
        ltl_pattern = re.compile(r"^---\s+LTL\s+(\w+)\s+---", re.MULTILINE)
        error_pattern = re.compile(r"errors:\s*(\d+)")

        current_prop = None
        for line in content.splitlines():
            ltl_match = ltl_pattern.search(line)
            if ltl_match:
                current_prop = ltl_match.group(1)
                continue

            if current_prop:
                error_match = error_pattern.search(line)
                if error_match:
                    error_count = int(error_match.group(1))
                    rules.append(
                        {
                            "name": current_prop,
                            "status": "PASS" if error_count == 0 else "FAIL",
                            "formula": current_prop,  # Could extract full formula if available
                            "errors": error_count,
                            "tool_specific": {"ltl_property": current_prop},
                        }
                    )
                    current_prop = None

        return rules if rules else self._extract_generic_results(content)

    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """
        Parse SPIN trace data.
        If trail_path is provided and exists, read from it.
        Otherwise, attempt to parse log_path as a trail file first; if that yields
        no steps, fall back to log parsing.
        """
        # Case 1: explicit trail file
        if trail_path and os.path.exists(trail_path):
            try:
                with open(trail_path, "r", errors="replace") as f:
                    trail_content = f.read()
                trace = self._parse_trail_output(trail_content)
                if trace.steps:
                    return trace
            except Exception:
                pass  # fall back to log-based parsing

        # Case 2: no explicit trail file; try to read log_path as trail content
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", errors="replace") as f:
                    content = f.read()
                trace = self._parse_trail_output(content)
                if trace.steps:
                    return trace
            except Exception:
                pass

        # Fallback: parse log as generic error log
        return self._parse_log_as_trace(log_path)

    def _parse_trail_output(self, trail_content: str) -> ExecutionTrace:
        """
        Parse SPIN trail replay output (from `spin -t -p -g model.pml`)
        Format: "N: proc P (Name) file:line (state S) [action]"
        """
        trace = ExecutionTrace()

        # Regex patterns for SPIN step lines
        pat_a = re.compile(
            r"^\s*(\d+):\s*proc\s+(\d+)\s*\(([^)]+)\)\s+(\S+):(\d+)\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?"
        )
        pat_b = re.compile(
            r"^\s*(\d+):\s*proc\s+(\d+)\s*\(([^)]+)\)\s+line\s+(\d+)\s+\"([^\"]+)\"\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?"
        )

        current_vars = {}
        error_found = False

        for line in trail_content.splitlines():
            m = pat_a.match(line) or pat_b.match(line)
            if m:
                groups = m.groups()
                step_num = int(groups[0])
                proc_id = int(groups[1])
                proc_name = groups[2].strip()
                line_num = groups[3]
                state_id = groups[5]
                action = (groups[6] or "").strip()

                file_name = groups[3] if pat_a.match(line) else groups[4]

                # Parse variable updates from action
                updates = {}
                if action:
                    for part in action.split(","):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            k = k.strip().lstrip("(")
                            v = v.strip().rstrip(")")
                            if re.match(r"^\w+$", k):
                                updates[k] = v
                                current_vars[k] = v

                is_error = (
                    "assert" in action.lower()
                    or "violation" in line.lower()
                    or "error" in line.lower()
                )
                if is_error:
                    error_found = True
                    trace.error_line = step_num

                step = TraceStep(
                    step_num=step_num,
                    proc=proc_name,
                    action=action,
                    state=state_id,
                    line=line_num,
                    file=file_name,
                    variables=current_vars.copy(),
                    updates=updates,
                    is_error=is_error,
                )
                trace.steps.append(step)

            # Capture LTL violation lines
            elif "ltl" in line.lower() or "assertion violated" in line.lower():
                trace.error_message = line.strip()
                error_found = True

        trace.final_variables = current_vars
        trace.final_state = trace.steps[-1].state if trace.steps else ""

        return trace

    def _parse_log_as_trace(self, log_path: str) -> ExecutionTrace:
        """Fallback: Extract what we can from the log file"""
        trace = ExecutionTrace()

        if not log_path or not os.path.exists(log_path):
            return trace

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return trace

        # Extract error/assertion lines as potential trace steps
        for i, line in enumerate(content.splitlines()[:100]):
            if any(k in line.lower() for k in ("error", "assert", "violation")):
                step = TraceStep(
                    step_num=i + 1,
                    proc="SPIN",
                    action=line.strip(),
                    state="unknown",
                    line=str(i),
                    file="",
                    is_error=True,
                )
                trace.steps.append(step)
                trace.error_line = i + 1
                trace.error_message = line.strip()

        return trace

    def _extract_generic_results(self, content: str) -> List[Dict]:
        """
        Fallback: Extract generic pass/fail status from log.
        Look for "errors: N" or "PASSED" / "FAILED"
        """
        rules = []

        if "PASSED" in content or "passed" in content:
            rules.append(
                {
                    "name": "verification",
                    "status": "PASS",
                    "formula": "SPIN verification",
                    "errors": 0,
                    "tool_specific": {},
                }
            )
        elif "FAILED" in content or "failed" in content:
            rules.append(
                {
                    "name": "verification",
                    "status": "FAIL",
                    "formula": "SPIN verification",
                    "errors": 1,
                    "tool_specific": {},
                }
            )

        return rules

    def get_recommendations(self, status: str) -> List[str]:
        """SPIN-specific recommendations"""
        if status == "FAIL":
            return [
                "Review the counterexample trace for the failing state path",
                "Check if the LTL property is too strict or incorrectly specified",
                "Verify that the Promela model accurately represents the contract",
                "Consider adding constraints to rule out spurious counterexamples",
            ]
        else:
            return [
                "The verification passed - the LTL properties hold for all possible states",
                "Consider verifying additional properties to increase confidence",
            ]
