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

    def _read_content(self, path_or_content: str) -> str:
        """Read content from file or return inline content"""
        if not path_or_content:
            return ""
        # If it looks like content (newlines or long string that isn't a path), return it
        if "\n" in path_or_content or (len(path_or_content) > 255 and not os.path.exists(path_or_content)):
            return path_or_content
        # Otherwise treat as path
        if os.path.exists(path_or_content):
            try:
                with open(path_or_content, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception:
                return ""
        return path_or_content

    def parse_rules(self, log_path: str) -> List[Dict]:
        """
        Extract LTL properties from SPIN log file.
        Format: "--- LTL property_name ---" followed by "errors: N"
        """
        # Handle inline content (inlined by sync_audit_log)
        content = self._read_content(log_path)
        if not content:
            return []

        rules = []
        # Pattern continues...

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
            trail_content = self._read_content(trail_path)
            if trail_content:
                trace = self._parse_trail_output(trail_content)
                if trace.steps:
                    return trace

        # Case 2: no explicit trail file; try to read log_path as trail content
        if log_path and os.path.exists(log_path):
            content = self._read_content(log_path)
            if content:
                trace = self._parse_trail_output(content)
                if trace.steps:
                    return trace

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

        if not log_path:
            return trace

        content = self._read_content(log_path)
        if not content:
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

    def _parse_inline_trail(self, trail_text: str) -> str:
        """
        Parse inline trail file content (format: -2:9:-2, 1:0:112, etc.)
        and convert to SPIN replay output format that _STEP_A/_STEP_B can parse.
        """
        # Trail format: line:proc:line_in_proc
        # We need to map this to something resembling the replay output
        # For now, just return a synthetic representation
        lines = []
        for i, raw in enumerate(trail_text.strip().splitlines()):
            raw = raw.strip()
            if not raw or raw.startswith("-"):
                continue
            parts = raw.split(":")
            if len(parts) >= 2:
                try:
                    step_num = i + 1
                    proc_id = parts[1] if len(parts) > 1 else "0"
                    line_num = parts[0] if len(parts) > 0 else "0"
                    lines.append(f"{step_num}:\tproc {proc_id}\t(Contract)\tline {line_num} \"step\" (state 0)")
                except Exception:
                    continue
        return "\n".join(lines)

    def _replay_trail(self, path: str) -> str:
        """Try to find and replay a .trail file near the given path."""
        candidates = []
        pml_candidates = []
        if path:
            d = os.path.dirname(path)
            candidates += [
                os.path.join(d, "translated_output.pml.trail"),
                os.path.join(d, "contract.pml.trail"),
                path if path.endswith(".trail") else path + ".trail",
            ]
            # Add pml candidates in the same directory
            pml_candidates += [
                os.path.join(d, "translated_output.pml"),
                os.path.join(d, "contract.pml"),
            ]
            # Try to find any .pml file in the same directory
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith(".pml"):
                        pml_candidates.append(os.path.join(d, f))
        
        # Also check project root
        root = os.path.dirname(os.path.dirname(__file__))
        candidates += [
            os.path.join(root, "generated", "models", "translated_output.pml.trail"),
            os.path.join(root, "translated_output.pml.trail"),
        ]
        pml_candidates += [
            os.path.join(root, "generated", "models", "translated_output.pml"),
        ]
        
        pml_file = next((p for p in pml_candidates if os.path.exists(p)), None)
        trail_file = next((p for p in candidates if os.path.exists(p)), None)

        if not trail_file or not pml_file:
            return ""
        try:
            import subprocess
            result = subprocess.run(
                ["spin", "-t", "-p", "-g", pml_file],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.dirname(pml_file),
            )
            return result.stdout or result.stderr
        except Exception:
            return ""

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
