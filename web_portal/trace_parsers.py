"""
DeFi Guardian - Trace Parsers
Unified parser interface for all verification tools.
Each parser converts raw tool output into structured TraceResult objects
that the web portal renders in the Certora-style 3-panel viewer.
"""

from __future__ import annotations
import os
import re
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TraceStep:
    step: int
    step_number: int = 0  # Alias for compatibility
    proc: str = ""
    line: int = 0
    file: str = ""
    source: str = ""  # Full source location like "contract.sol:123"
    state: str = ""
    action: str = ""
    variables: dict = field(default_factory=dict)
    variables_before: dict = field(default_factory=dict)
    variables_after: dict = field(default_factory=dict)
    updates: dict = field(default_factory=dict)
    is_error: bool = False

    def __post_init__(self):
        # Ensure step_number matches step for compatibility
        if self.step_number == 0 and self.step > 0:
            self.step_number = self.step
        elif self.step == 0 and self.step_number > 0:
            self.step = self.step_number

    def to_dict(self):
        return asdict(self)


@dataclass
class TraceResult:
    steps: list[TraceStep] = field(default_factory=list)
    final_variables: dict = field(default_factory=dict)
    error_message: str = ""
    tool: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "steps": [s.to_dict() for s in self.steps],
            "final_variables": self.final_variables,
            "error_message": self.error_message,
            "tool": self.tool,
            "warnings": self.warnings,
        }


@dataclass
class RuleResult:
    name: str
    status: str          # "VERIFIED" | "VIOLATED" | "TIMEOUT" | "ERROR" | "UNKNOWN"
    formula: str = ""
    category: str = ""
    message: str = ""
    errors: int = 0

    def to_dict(self):
        return asdict(self)


def classify_property(formula: str) -> str:
    if not formula:
        return ""
    if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b|until", formula, re.IGNORECASE):
        return "LIVENESS"
    if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE):
        return "SAFETY"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Base parser
# ─────────────────────────────────────────────────────────────────────────────

class BaseParser:
    tool_name = "UNKNOWN"

    def parse_rules(self, log_path: str) -> list[dict]:
        """Return list of RuleResult dicts."""
        return []

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        """Return a TraceResult or None."""
        return None

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        return []

    _FILE_LINE = re.compile(r'(?:(?:at|in)\s+)?(?P<file>[\w./\\-]+\.\w+):(?P<line>\d+)\b')
    _LINE_ONLY = re.compile(r'\bline\s+(?P<line>\d+)\b', re.IGNORECASE)
    _VAR_ASSIGN = re.compile(r'(?<![=!<>])\b([A-Za-z_]\w*)\s*(?:=|:=)\s*(?![=<>])([-+]?0x[0-9A-Fa-f]+|[-+]?\d+|true|false)\b', re.IGNORECASE)

    def _read(self, path_or_content: str) -> str:
        if not path_or_content:
            return ""
        # Check for inline trail marker (inlined by sync_audit_log)
        if "=== TRAIL TRACE ===" in path_or_content:
            return path_or_content
        # Check for LOG_NOT_FOUND marker - strip it but keep the rest for parsing
        if path_or_content.startswith("[LOG_NOT_FOUND:"):
            # Extract the synthetic content after the marker line
            parts = path_or_content.split("\n", 1)
            if len(parts) > 1:
                return parts[1]
            return ""
            
        # Heuristic to detect if it's a file path
        is_path_like = (
            ("/" in path_or_content or "\\" in path_or_content or path_or_content.endswith((".log", ".txt", ".pml", ".sol", ".rs", ".trail")))
            and " " not in path_or_content
        )
        
        if os.path.exists(path_or_content):
            try:
                with open(path_or_content, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception:
                return ""
        elif is_path_like:
            return ""
            
        # If it looks like content (newlines or long string that isn't a path), return it
        if "\n" in path_or_content or len(path_or_content) > 255:
            return path_or_content
        return path_or_content

    def _extract_line_info(self, text: str) -> tuple[int, str]:
        m = self._FILE_LINE.search(text)
        if m:
            return int(m.group("line")), m.group("file")
        m = self._LINE_ONLY.search(text)
        if m:
            return int(m.group("line")), ""
        return 0, ""

    def _extract_variables(self, text: str) -> dict:
        vars: dict[str, str] = {}
        for m in self._VAR_ASSIGN.finditer(text):
            name = m.group(1)
            val = m.group(2).strip()
            vars[name] = val
        return vars

    def _parse_basic_trace(self, text: str, proc_name: str = "") -> TraceResult:
        steps: list[TraceStep] = []
        current_vars: dict = {}
        warnings: list[str] = []

        for i, raw_line in enumerate(text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue

            line_num, file_name = self._extract_line_info(line)
            vars_here = self._extract_variables(line)
            prev_vars = dict(current_vars)
            if vars_here:
                current_vars.update(vars_here)

            # Build source location string
            source_parts = []
            if file_name:
                source_parts.append(file_name)
            if line_num > 0:
                source_parts.append(f"line {line_num}")
            source = ": ".join(source_parts) if source_parts else ""

            is_err = False
            if hasattr(self, '_ERROR') and getattr(self, '_ERROR') is not None:
                try:
                    is_err = bool(self._ERROR.search(line))
                except Exception:
                    is_err = False
            if not is_err:
                is_err = bool(re.search(r'error|fail|violat|exception|assert', line, re.IGNORECASE))

            if re.search(r'^(warning|note)\b[: ]', line, re.IGNORECASE):
                warnings.append(line)

            steps.append(TraceStep(
                step=len(steps) + 1,
                proc=proc_name or self.tool_name.lower(),
                line=line_num,
                file=file_name,
                source=source,
                action=line[:200],
                variables=dict(current_vars),
                variables_before=prev_vars,
                variables_after=dict(current_vars),
                updates=vars_here,
                is_error=is_err,
            ))

        error_msg = ""
        if any(s.is_error for s in steps):
            error_msg = "Property violation or error detected in execution trace."

        return TraceResult(
            steps=steps,
            final_variables=current_vars,
            error_message=error_msg,
            tool=self.tool_name,
            warnings=warnings,
        )


# ─────────────────────────────────────────────────────────────────────────────
# SPIN parser
# ─────────────────────────────────────────────────────────────────────────────

class SpinParser(BaseParser):
    tool_name = "SPIN"

    # Patterns for SPIN 6.x replay output
    _STEP_A = re.compile(
        r"^\s*(\d+):\s*proc\s+(\d+)\s*\(([^)]+)\)\s+"
        r"(?:\S+):(\d+)\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?"
    )
    _STEP_B = re.compile(
        r"^\s*(\d+):\s*proc\s+(\d+)\s*\(([^)]+)\)\s+"
        r'line\s+(\d+)\s+"[^"]+"\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?'
    )
    _VAR = re.compile(r"^\s+([A-Za-z_]\w*)\s*=\s*(?![=<>])(.+)$")
    _LTL = re.compile(
        r"---\s*LTL\s+(\w+)\s*---.*?errors:\s*(\d+)",
        re.DOTALL,
    )
    _LTL_FORMULA = re.compile(r"ltl\s+(\w+)\s*\{([^}]+)\}")

    def parse_rules(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []

        formulas: dict[str, str] = {}
        for m in self._LTL_FORMULA.finditer(text):
            formulas[m.group(1).strip()] = m.group(2).strip()

        rules: list[dict] = []
        for m in self._LTL.finditer(text):
            name = m.group(1)
            errors = int(m.group(2))
            status = "VERIFIED" if errors == 0 else "VIOLATED"
            rules.append(RuleResult(
                name=name,
                status=status,
                formula=formulas.get(name, ""),
                category=classify_property(formulas.get(name, "") or name),
                errors=errors,
            ).to_dict())

        # Fallback: read from verification_state.json
        if not rules:
            rules = self._rules_from_state_json()

        # If we have formulas but no LTL results, infer from names
        if formulas and not rules:
            for name, formula in formulas.items():
                rules.append(RuleResult(
                    name=name,
                    status="UNKNOWN",
                    formula=formula,
                    category=classify_property(formula),
                    errors=0,
                ).to_dict())

        return rules

    def _rules_from_state_json(self) -> list[dict]:
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "verification_state.json"),
        ]
        for p in candidates:
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        data = json.load(f)
                    ltl = data.get("ltl_results") or data.get("spin", {}).get("ltl_results", [])
                    return [
                        RuleResult(
                            name=r.get("name", ""),
                            status="VERIFIED" if r.get("success") else "VIOLATED",
                            formula=r.get("formula", ""),
                            category=classify_property(r.get("formula", "") or r.get("name", "")),
                            errors=r.get("errors", 0),
                        ).to_dict()
                        for r in ltl
                    ]
                except Exception:
                    pass
        return []

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        # 1. Check for inline trail content (inlined by sync_audit_log)
        text = self._read(log_path)
        trail_text = ""

        # Extract inline trail if present
        if "=== TRAIL TRACE ===" in text:
            parts = text.split("=== TRAIL TRACE ===")
            if len(parts) > 1:
                trail_text = parts[1].split("=== LOG OUTPUT ===")[0]
                # Parse trail format into steps
                trail_text = self._parse_inline_trail(trail_text)

        # 2. Try to replay the trail file from filesystem
        if not trail_text:
            trail_text = self._replay_trail(report_path or log_path)

        # 3. Fallback to reading log content directly
        if not trail_text:
            trail_text = text

        if not trail_text:
            return None

        steps: list[TraceStep] = []
        current_vars: dict = {}
        prev_vars: dict = {}

        for raw_line in trail_text.splitlines():
            m = self._STEP_A.match(raw_line) or self._STEP_B.match(raw_line)
            if m:
                groups = m.groups()
                step_num = int(groups[0])
                proc_id  = groups[1]
                proc_name = groups[2]
                line_num  = int(groups[3])
                state_id  = groups[4]
                action    = (groups[5] or "").strip()

                is_err = (
                    "assert" in action.lower()
                    or "violation" in action.lower()
                    or "error" in action.lower()
                )

                prev_vars = dict(current_vars)
                ts = TraceStep(
                    step=step_num,
                    proc=f"proc {proc_id} ({proc_name})",
                    line=line_num,
                    source=f"line {line_num}",
                    state=f"state {state_id}",
                    action=action,
                    variables=dict(current_vars),
                    variables_before=prev_vars,
                    variables_after=dict(current_vars),
                    updates={},
                    is_error=is_err,
                )
                steps.append(ts)
                continue

            vm = self._VAR.match(raw_line)
            if vm and steps:
                var_name = vm.group(1)
                var_val  = vm.group(2).strip()
                old_val  = current_vars.get(var_name)
                current_vars[var_name] = var_val
                if old_val != var_val:
                    steps[-1].updates[var_name] = var_val
                steps[-1].variables[var_name] = var_val
                steps[-1].variables_before = dict(prev_vars)
                steps[-1].variables_after = dict(current_vars)

        error_msg = ""
        if any(s.is_error for s in steps):
            error_msg = "LTL property violation detected in execution trace."

        # If no steps were parsed, create a synthetic step from log content
        if not steps and text:
            error_match = re.search(r"errors:\s*(\d+)", text)
            errors = int(error_match.group(1)) if error_match else 0
            if errors > 0:
                steps.append(TraceStep(
                    step=1,
                    proc="spin",
                    line=0,
                    source="",
                    state="",
                    action="LTL property violation detected",
                    variables={},
                    variables_before={},
                    variables_after={},
                    updates={},
                    is_error=True,
                ))
                error_msg = "LTL property violation detected in execution trace."

        # Extract unreached sections as warnings
        warnings = []
        if trail_text:
            for line in trail_text.splitlines():
                if "unreached in" in line:
                    warnings.append(line.strip())

        return TraceResult(
            steps=steps,
            final_variables=current_vars,
            error_message=error_msg,
            tool="SPIN",
            warnings=warnings,
        )

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

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return [
                "All LTL properties verified — no counterexample found.",
                "Consider adding more invariants to strengthen the specification.",
                "Run mutation testing with Gambit to validate rule coverage.",
            ]

        recommendations = []
        text = self._read(log_path) if log_path else ""
        lower_text = text.lower()
        if "acceptance cycle" in lower_text:
            recommendations.append(
                "This failure appears as an acceptance cycle, indicating a liveness/fairness issue rather than a simple safety assertion."
            )
        elif "assertion violated" in lower_text or "assert(" in lower_text:
            recommendations.append(
                "An assertion failure was detected. Inspect the predicate and the variable state at the failing step."
            )
        else:
            recommendations.append(
                "A counterexample was found. Review the trace and variable state to determine whether this is a safety or liveness violation."
            )

        if "unreached in" in lower_text:
            recommendations.append(
                "Some model sections were never reached during search; that may indicate dead or unreachable behavior."
            )

        recommendations.extend([
            "Review the violated LTL property and ensure the model encodes the expected behavior.",
            "Inspect variable values at each step to identify the root cause.",
            "Consider adding require() guards or fairness constraints depending on the failure type.",
        ])
        return recommendations


# ─────────────────────────────────────────────────────────────────────────────
# Coq parser
# ─────────────────────────────────────────────────────────────────────────────

class CoqParser(BaseParser):
    tool_name = "COQ"

    _THEOREM = re.compile(r"Theorem\s+(\w+)\s*:", re.MULTILINE)
    _QED     = re.compile(r"\bQed\b")
    _ADMIT   = re.compile(r"\bAdmitted\b")
    _ERROR   = re.compile(r"^Error:", re.MULTILINE)

    def parse_rules(self, log_path: str) -> list[dict]:
        # Try to read the spec (Coq script) from audit_log
        spec_text = self._get_spec(log_path)
        if not spec_text:
            return self._rules_from_log(log_path)

        theorems = self._THEOREM.findall(spec_text)
        qeds     = len(self._QED.findall(spec_text))
        admits   = len(self._ADMIT.findall(spec_text))

        rules = []
        for i, name in enumerate(theorems):
            if i < qeds:
                status = "VERIFIED"
            elif i < qeds + admits:
                status = "TIMEOUT"   # Admitted = deferred
            else:
                status = "UNKNOWN"
            rules.append(RuleResult(name=name, status=status).to_dict())
        return rules

    def _get_spec(self, log_path: str) -> str:
        # Try audit_log.json for the spec
        root = os.path.dirname(os.path.dirname(__file__))
        audit_log = os.path.join(root, "generated", "reports", "audit_log.json")
        if os.path.exists(audit_log):
            try:
                with open(audit_log) as f:
                    jobs = json.load(f)
                for job in jobs:
                    if job.get("tool", "").upper() == "COQ":
                        return job.get("specs", "")
            except Exception:
                pass
        return ""

    def _rules_from_log(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []
        errors = self._ERROR.findall(text)
        if errors:
            return [RuleResult(name="coq_proof", status="ERROR", message=text[:500]).to_dict()]
        return [RuleResult(name="coq_proof", status="VERIFIED").to_dict()]

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="coqc")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return [
                "Coq proofs completed. Admitted theorems require manual proof.",
                "Replace 'admit' tactics with actual proof terms for full verification.",
            ]
        return [
            "Coq compilation failed. Check the error message in the log.",
            "Common issues: type mismatches, missing imports, or incorrect tactics.",
            "Ensure Coq and required libraries (Lia, Arith) are installed.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Lean parser
# ─────────────────────────────────────────────────────────────────────────────

class LeanParser(BaseParser):
    tool_name = "LEAN"

    _THEOREM = re.compile(r"theorem\s+(\w+)", re.MULTILINE)
    _SORRY   = re.compile(r"\bsorry\b")
    _ERROR   = re.compile(r"^error:", re.MULTILINE | re.IGNORECASE)

    def parse_rules(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []
        theorems = self._THEOREM.findall(text)
        errors   = bool(self._ERROR.search(text))
        rules = []
        for name in theorems:
            status = "ERROR" if errors else "VERIFIED"
            rules.append(RuleResult(name=name, status=status).to_dict())
        if not rules:
            rules.append(RuleResult(
                name="lean_proof",
                status="ERROR" if errors else "VERIFIED",
            ).to_dict())
        return rules

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="lean")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return ["Lean 4 theorems proved successfully."]
        return [
            "Lean proof failed. Check for 'sorry' placeholders.",
            "Ensure lake build succeeds before running verification.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Certora parser
# ─────────────────────────────────────────────────────────────────────────────

class CertoraParser(BaseParser):
    tool_name = "CERTORA"

    _RULE    = re.compile(r"rule\s+(\w+)", re.MULTILINE)
    _PASS    = re.compile(r"\[PASS\]|verified|VERIFIED", re.IGNORECASE)
    _FAIL    = re.compile(r"\[FAIL\]|violated|VIOLATED|counterexample", re.IGNORECASE)
    _TIMEOUT = re.compile(r"timeout|TIMEOUT", re.IGNORECASE)

    def parse_rules(self, log_path: str) -> list[dict]:
        # Try to get spec from audit_log
        spec_text = self._get_spec()
        log_text  = self._read(log_path)

        rules: list[dict] = []
        if spec_text:
            for m in self._RULE.finditer(spec_text):
                name = m.group(1)
                if log_text:
                    if self._FAIL.search(log_text):
                        status = "VIOLATED"
                    elif self._PASS.search(log_text):
                        status = "VERIFIED"
                    elif self._TIMEOUT.search(log_text):
                        status = "TIMEOUT"
                    else:
                        status = "UNKNOWN"
                else:
                    status = "UNKNOWN"
                rules.append(RuleResult(name=name, status=status).to_dict())

        if not rules:
            rules.append(RuleResult(
                name="certora_rule",
                status="VIOLATED" if self._FAIL.search(log_text or "") else "UNKNOWN",
            ).to_dict())
        return rules

    def _get_spec(self) -> str:
        root = os.path.dirname(os.path.dirname(__file__))
        audit_log = os.path.join(root, "generated", "reports", "audit_log.json")
        if os.path.exists(audit_log):
            try:
                with open(audit_log) as f:
                    jobs = json.load(f)
                for job in jobs:
                    if job.get("tool", "").upper() == "CERTORA":
                        return job.get("specs", "")
            except Exception:
                pass
        return ""

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="certora")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return [
                "Certora rules verified. Consider adding parametric rules.",
                "Use ghost variables to track cross-function state.",
            ]
        return [
            "Certora found a counterexample. Review the call trace.",
            "Check require() preconditions in your CVL rules.",
            "Ensure the Certora CLI is configured with a valid API key.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Kani / Rust parser
# ─────────────────────────────────────────────────────────────────────────────

class KaniParser(BaseParser):
    tool_name = "KANI"

    _CHECK  = re.compile(r"VERIFICATION:- (SUCCESSFUL|FAILED)", re.IGNORECASE)
    _PROP   = re.compile(r"Check \d+: (.+?) - (SATISFIED|FAILED|UNDETERMINED)", re.IGNORECASE)

    def parse_rules(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []
        rules = []
        for m in self._PROP.finditer(text):
            name   = m.group(1).strip()
            result = m.group(2).upper()
            status = "VERIFIED" if result == "SATISFIED" else "VIOLATED"
            rules.append(RuleResult(name=name, status=status).to_dict())
        if not rules:
            m = self._CHECK.search(text)
            status = "VERIFIED" if m and "SUCCESSFUL" in m.group(1).upper() else "VIOLATED"
            rules.append(RuleResult(name="kani_harness", status=status).to_dict())
        return rules

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="kani")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return ["Kani bounded model checking passed. No panics or overflows found."]
        return [
            "Kani found a counterexample. Check for integer overflows or panics.",
            "Add #[kani::proof] harnesses with concrete bounds.",
            "Use kani::assume() to constrain inputs.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Prusti parser
# ─────────────────────────────────────────────────────────────────────────────

class PrustiParser(BaseParser):
    tool_name = "PRUSTI"

    _PASS = re.compile(r"Verification successful", re.IGNORECASE)
    _FAIL = re.compile(r"Verification error|postcondition might not hold|precondition might not hold", re.IGNORECASE)

    def parse_rules(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []
        if self._PASS.search(text):
            return [RuleResult(name="prusti_verification", status="VERIFIED").to_dict()]
        if self._FAIL.search(text):
            return [RuleResult(name="prusti_verification", status="VIOLATED", message=text[:300]).to_dict()]
        return [RuleResult(name="prusti_verification", status="UNKNOWN").to_dict()]

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="prusti")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return ["Prusti deductive verification passed."]
        return [
            "Prusti found a specification violation.",
            "Check #[requires] and #[ensures] annotations.",
            "Ensure loop invariants are correctly specified.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Verus parser
# ─────────────────────────────────────────────────────────────────────────────

class VerusParser(BaseParser):
    tool_name = "VERUS"

    _PASS = re.compile(r"verification results:: \d+ verified", re.IGNORECASE)
    _FAIL = re.compile(r"\d+ errors", re.IGNORECASE)

    def parse_rules(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []
        if self._PASS.search(text):
            return [RuleResult(name="verus_proof", status="VERIFIED").to_dict()]
        if self._FAIL.search(text):
            return [RuleResult(name="verus_proof", status="VIOLATED").to_dict()]
        return [RuleResult(name="verus_proof", status="UNKNOWN").to_dict()]

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="verus")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return ["Verus SMT-based verification passed."]
        return [
            "Verus found a proof obligation failure.",
            "Check requires/ensures clauses in verus! macro blocks.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Creusot parser
# ─────────────────────────────────────────────────────────────────────────────

class CreusotParser(BaseParser):
    tool_name = "CREUSOT"

    def parse_rules(self, log_path: str) -> list[dict]:
        text = self._read(log_path)
        if not text:
            return []
        if "error" in text.lower():
            return [RuleResult(name="creusot_proof", status="VIOLATED").to_dict()]
        return [RuleResult(name="creusot_proof", status="VERIFIED").to_dict()]

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        text = self._read(log_path)
        if not text:
            return None
        return self._parse_basic_trace(text, proc_name="creusot")

    def get_recommendations(self, status: str, log_path: str = "") -> list[str]:
        if status == "PASS":
            return ["Creusot Why3 verification passed."]
        return [
            "Creusot proof failed. Check #[requires] and #[ensures] attributes.",
            "Ensure Why3 and the required provers (Alt-Ergo, Z3) are installed.",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_PARSERS: dict[str, BaseParser] = {
    "SPIN":    SpinParser(),
    "COQ":     CoqParser(),
    "LEAN":    LeanParser(),
    "CERTORA": CertoraParser(),
    "KANI":    KaniParser(),
    "PRUSTI":  PrustiParser(),
    "VERUS":   VerusParser(),
    "CREUSOT": CreusotParser(),
}


def get_parser(tool: str) -> Optional[BaseParser]:
    """Return the parser for the given tool name (case-insensitive)."""
    return _PARSERS.get((tool or "").upper())


def list_parsers() -> list[str]:
    return list(_PARSERS.keys())
