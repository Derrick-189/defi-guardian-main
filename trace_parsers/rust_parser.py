"""Rust verification tools trace parser (Kani, Prusti, Creusot)."""

import re
import os
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep
from trace_parsers import TraceParser


class RustParser(TraceParser):
    """Unified parser for Rust verification tools (Kani, Prusti, Creusot)"""

    def __init__(self, tool: str):
        self.tool = tool.upper()  # KANI, PRUSTI, or CREUSOT

    # -------------------------------------------------------------------------
    # Public interfaces
    # -------------------------------------------------------------------------
    def parse_rules(self, log_path: str) -> List[Dict]:
        """Extract verification results based on tool type"""
        if not log_path or not os.path.exists(log_path):
            return []

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        rules = []

        if self.tool == "KANI":
            rules = self._parse_kani_checks(content)
        elif self.tool == "PRUSTI":
            rules = self._parse_prusti_specs(content)
        elif self.tool == "CREUSOT":
            rules = self._parse_creusot_results(content)

        if not rules:
            status = "PASS" if "verified" in content.lower() else "FAIL"
            rules.append(
                {
                    "name": f"{self.tool} Verification",
                    "status": status,
                    "formula": f"{self.tool} verification",
                    "errors": 0 if status == "PASS" else 1,
                    "tool_specific": {"tool": self.tool},
                }
            )

        return rules

    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """Extract detailed trace for Rust verification tools."""
        trace = ExecutionTrace()

        if not log_path or not os.path.exists(log_path):
            return trace

        try:
            with open(log_path, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return trace

        if self.tool == "KANI":
            trace = self._parse_kani_trace(content)
        elif self.tool == "PRUSTI":
            trace = self._parse_prusti_trace(content)
        elif self.tool == "CREUSOT":
            trace = self._parse_creusot_trace(content)
        else:
            # Fallback generic: collect lines that look like errors
            for i, line in enumerate(content.splitlines()):
                if any(kw in line.lower() for kw in ("error", "panicked", "failed", "violation")):
                    step = TraceStep(
                        step_num=len(trace.steps) + 1,
                        proc=self.tool,
                        action=line.strip(),
                        state="error",
                        line=str(i),
                        file="",
                        is_error=True,
                    )
                    trace.steps.append(step)
            if trace.steps:
                trace.error_line = trace.steps[0].step_num
                trace.error_message = trace.steps[0].action

        # Set final state from last step if available
        if trace.steps:
            last = trace.steps[-1]
            trace.final_state = last.state
            trace.final_variables = last.variables

        return trace

    # -------------------------------------------------------------------------
    # Kani parsers
    # -------------------------------------------------------------------------
    def _parse_kani_checks(self, content: str) -> List[Dict]:
        """Parse Kani verification results (both compact and verbose formats)."""
        rules = []
        current = None
        step_counter = 1

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.lower().startswith("check "):
                if current is not None:
                    rule = self._kani_check_to_rule(current, step_counter)
                    rules.append(rule)
                    step_counter += 1

                header_match = re.match(r'Check\s+(\d+):\s*(.+)', line, re.IGNORECASE)
                if not header_match:
                    current = None
                    continue

                check_id = header_match.group(1)
                rest = header_match.group(2).strip()

                status = None
                name = rest
                m_status = re.search(r'\b(SUCCESS|PASSED|FAILURE|FAILED)\b', rest, re.IGNORECASE)
                if m_status:
                    token = m_status.group(1).upper()
                    status = "PASS" if token in ("SUCCESS", "PASSED") else "FAIL"
                    name = rest[:m_status.start()].strip()

                current = {
                    "id": check_id,
                    "name": name,
                    "status": status,
                    "description": None,
                    "file": None,
                    "line": None,
                    "function": None,
                }
                continue

            if current is not None:
                sline = line
                if sline.startswith("- Status:"):
                    status_str = sline.split(":", 1)[1].strip()
                    if "SUCCESS" in status_str.upper():
                        current["status"] = "PASS"
                    elif "FAILURE" in status_str.upper() or "FAILED" in status_str.upper():
                        current["status"] = "FAIL"
                elif sline.startswith("- Description:"):
                    desc = sline.split(":", 1)[1].strip()
                    if desc.startswith('"') and desc.endswith('"'):
                        desc = desc[1:-1]
                    current["description"] = desc
                elif sline.startswith("- Location:"):
                    loc = sline.split(":", 1)[1].strip()
                    m_loc = re.search(r'(\S+?):(\d+):(\d+)\s+in\s+function\s+(.+)', loc)
                    if m_loc:
                        current["file"] = m_loc.group(1)
                        current["line"] = m_loc.group(2)
                        current["function"] = m_loc.group(4)
                    else:
                        parts = loc.split(":")
                        if len(parts) >= 2 and parts[1].isdigit():
                            current["file"] = parts[0]
                            current["line"] = parts[1]

        if current is not None:
            rule = self._kani_check_to_rule(current, step_counter)
            rules.append(rule)

        return rules

    def _kani_check_to_rule(self, check: dict, rule_idx: int) -> Dict:
        """Convert a parsed Kani check dict into a rule dict."""
        check_id = check.get("id", str(rule_idx))
        name = check.get("name") or f"check_{check_id}"
        status = check.get("status") or "PASS"
        description = check.get("description") or f"Check {check_id}"
        file = check.get("file") or ""
        line = check.get("line") or ""
        function = check.get("function") or ""

        return {
            "name": f"check_{check_id}_{name.replace('.', '_')}",
            "status": status,
            "formula": description,
            "errors": 0 if status == "PASS" else 1,
            "tool_specific": {
                "check_id": check_id,
                "file": file,
                "line": line,
                "function": function,
            },
        }

    def _parse_kani_trace(self, content: str) -> ExecutionTrace:
        """Parse Kani verification output to produce a step per failed check."""
        trace = ExecutionTrace()
        step_counter = 1
        current = None

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.lower().startswith("check "):
                if current is not None and current.get("status") == "FAIL":
                    step = self._kani_check_to_trace_step(current, step_counter)
                    if step:
                        trace.steps.append(step)
                        if trace.error_line == -1:
                            trace.error_line = step.step_num
                            trace.error_message = step.action
                        step_counter += 1

                header_match = re.match(r'Check\s+(\d+):\s*(.+)', line, re.IGNORECASE)
                if not header_match:
                    current = None
                    continue
                check_id = header_match.group(1)
                rest = header_match.group(2).strip()
                status = None
                name = rest
                m_status = re.search(r'\b(SUCCESS|PASSED|FAILURE|FAILED)\b', rest, re.IGNORECASE)
                if m_status:
                    token = m_status.group(1).upper()
                    status = "PASS" if token in ("SUCCESS", "PASSED") else "FAIL"
                    name = rest[:m_status.start()].strip()
                current = {
                    "id": check_id,
                    "name": name,
                    "status": status,
                    "description": None,
                    "file": None,
                    "line": None,
                    "function": None,
                }
            elif current is not None:
                sline = line
                if sline.startswith("- Status:"):
                    status_str = sline.split(":", 1)[1].strip()
                    if "SUCCESS" in status_str.upper():
                        current["status"] = "PASS"
                    elif "FAILURE" in status_str.upper() or "FAILED" in status_str.upper():
                        current["status"] = "FAIL"
                elif sline.startswith("- Description:"):
                    desc = sline.split(":", 1)[1].strip()
                    if desc.startswith('"') and desc.endswith('"'):
                        desc = desc[1:-1]
                    current["description"] = desc
                elif sline.startswith("- Location:"):
                    loc = sline.split(":", 1)[1].strip()
                    m_loc = re.search(r'(\S+?):(\d+):(\d+)\s+in\s+function\s+(.+)', loc)
                    if m_loc:
                        current["file"] = m_loc.group(1)
                        current["line"] = m_loc.group(2)
                        current["function"] = m_loc.group(4)
                    else:
                        parts = loc.split(":")
                        if len(parts) >= 2 and parts[1].isdigit():
                            current["file"] = parts[0]
                            current["line"] = parts[1]

        if current is not None and current.get("status") == "FAIL":
            step = self._kani_check_to_trace_step(current, step_counter)
            if step:
                trace.steps.append(step)
                if trace.error_line == -1:
                    trace.error_line = step.step_num
                    trace.error_message = step.action

        return trace

    def _kani_check_to_trace_step(self, check: dict, step_num: int) -> Optional[TraceStep]:
        """Create a TraceStep from a Kani check dict."""
        if not check:
            return None
        description = check.get("description") or f"Check {check.get('id','')} failed"
        proc = check.get("function") or "Kani"
        file = check.get("file") or ""
        line = check.get("line") or ""
        return TraceStep(
            step_num=step_num,
            proc=proc,
            action=description,
            state="failure",
            line=line,
            file=file,
            variables={},
            updates={},
            is_error=True,
        )

    # -------------------------------------------------------------------------
    # Prusti parsers
    # -------------------------------------------------------------------------
    def _parse_prusti_specs(self, content: str) -> List[Dict]:
        """Parse Prusti spec verification results (unchanged from original)"""
        rules = []
        spec_pattern = re.compile(r"(precondition|postcondition|invariant)\s+(\w+).*?.*?(error|verified)?", re.IGNORECASE | re.DOTALL)
        has_error = "error" in content.lower()

        for match in spec_pattern.finditer(content):
            spec_type = match.group(1)
            spec_name = match.group(2)
            rules.append(
                {
                    "name": f"{spec_type}_{spec_name}",
                    "status": "FAIL" if has_error else "PASS",
                    "formula": f"{spec_type} {spec_name}",
                    "errors": 1 if has_error else 0,
                    "tool_specific": {"spec_type": spec_type},
                }
            )

        return rules

    def _parse_prusti_trace(self, content: str) -> ExecutionTrace:
        """Parse Prusti output to extract counterexample variables per error."""
        trace = ExecutionTrace()
        lines = content.splitlines()
        i = 0
        step_counter = 1

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            is_error_line = False
            if "[Prusti: verification error]" in stripped:
                is_error_line = True
            elif stripped.lower().startswith("error:") or (stripped.lower().startswith("[prusti") and "error" in stripped.lower()):
                is_error_line = True

            if is_error_line:
                error_msg = stripped
                file = ""
                line_num = ""
                m = re.search(r'(\S+?\.rs):(\d+):(\d+)', stripped)
                if m:
                    file = m.group(1)
                    line_num = m.group(2)

                i += 1
                variables = {}
                while i < len(lines) and (lines[i].startswith("    ") or lines[i].strip() == ""):
                    sub = lines[i].strip()
                    m_var = re.search(r'counterexample for "(\w+)"', sub)
                    if m_var:
                        var_name = m_var.group(1)
                        initial_val = None
                        final_val = None
                        i += 1
                        while i < len(lines) and lines[i].startswith("        "):
                            val_line = lines[i].strip()
                            if val_line.startswith("initial value:"):
                                initial_val = val_line.split(":", 1)[1].strip()
                            elif val_line.startswith("final value:"):
                                final_val = val_line.split(":", 1)[1].strip()
                            i += 1
                        val_dict = {}
                        if initial_val is not None:
                            val_dict["initial"] = initial_val
                        if final_val is not None:
                            val_dict["final"] = final_val
                        variables[var_name] = val_dict
                        continue
                    else:
                        i += 1

                step = TraceStep(
                    step_num=step_counter,
                    proc="Prusti",
                    action=error_msg,
                    state="error",
                    line=line_num,
                    file=file,
                    variables=variables,
                    updates={},
                    is_error=True,
                )
                trace.steps.append(step)
                if step_counter == 1:
                    trace.error_line = step.step_num
                    trace.error_message = error_msg
                step_counter += 1
                continue
            else:
                i += 1

        return trace

    # -------------------------------------------------------------------------
    # Creusot parsers
    # -------------------------------------------------------------------------
    def _parse_creusot_results(self, content: str) -> List[Dict]:
        """Parse Creusot verification results"""
        rules = []
        has_error = "error" in content.lower() or "failed" in content.lower()
        rules.append(
            {
                "name": "Creusot Verification",
                "status": "FAIL" if has_error else "PASS",
                "formula": "Why3 deductive verification",
                "errors": 1 if has_error else 0,
                "tool_specific": {"backend": "Why3"},
            }
        )
        return rules

    def _parse_creusot_trace(self, content: str) -> ExecutionTrace:
        """Creusot currently doesn't produce structured traces; fallback to generic."""
        trace = ExecutionTrace()
        for i, line in enumerate(content.splitlines()):
            if "error" in line.lower() or "failed" in line.lower():
                step = TraceStep(
                    step_num=len(trace.steps) + 1,
                    proc="Creusot",
                    action=line.strip(),
                    state="error",
                    line=str(i),
                    file="",
                    is_error=True,
                )
                trace.steps.append(step)
                if not trace.error_line:
                    trace.error_line = step.step_num
                    trace.error_message = line.strip()
        return trace

    # -------------------------------------------------------------------------
    # Recommendations
    # -------------------------------------------------------------------------
    def get_recommendations(self, status: str) -> List[str]:
        if self.tool == "KANI":
            if status == "FAIL":
                return [
                    "Check for panics in your code",
                    "Verify buffer bounds on array accesses",
                    "Ensure arithmetic operations don't overflow",
                ]
            return ["All checks passed - code is verified"]

        elif self.tool == "PRUSTI":
            if status == "FAIL":
                return [
                    "Check precondition specifications match function behavior",
                    "Verify postcondition specifications are achievable",
                    "Review loop invariants for completeness",
                ]
            return ["Prusti specifications verified"]

        elif self.tool == "CREUSOT":
            if status == "FAIL":
                return [
                    "Check Why3 backend integration",
                    "Verify proof annotations are correct",
                    "Review SMT solver output",
                ]
            return ["Creusot verification successful"]

        return ["Verification complete"]
