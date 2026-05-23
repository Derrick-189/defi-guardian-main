"""
DeFi Guardian — Slither-powered specification extractor.

Runs Slither static analysis on Solidity contracts and converts
findings into LTL properties, Certora rules, and Promela invariants
that can be loaded directly into the spec editor.
"""

from __future__ import annotations

import os
import re
import subprocess
import json
from typing import Any


class SlitherSpecExtractor:
    """Extract specifications using Slither's static analysis."""

    def __init__(self):
        self.slither_available = self._check_slither()

    # ── availability ──────────────────────────────────────────────────

    def _check_slither(self) -> bool:
        try:
            subprocess.run(
                ["slither", "--version"],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False

    # ── core extraction ───────────────────────────────────────────────

    def extract_invariants(self, solidity_file: str) -> dict[str, Any]:
        """
        Run Slither on *solidity_file* and return a structured dict of
        invariants, access-control findings, and reentrancy warnings.
        """
        if not self.slither_available:
            return {
                "error": (
                    "Slither not installed. "
                    "Run: pip install slither-analyzer"
                )
            }

        if not os.path.exists(solidity_file):
            return {"error": f"File not found: {solidity_file}"}

        invariants: list[dict] = []
        raw_outputs: list[str] = []

        # ── 1. vars-and-auth printer ──────────────────────────────────
        r = subprocess.run(
            ["slither", solidity_file, "--print", "vars-and-auth"],
            capture_output=True, text=True, timeout=60
        )
        raw_outputs.append(r.stdout)

        for line in r.stdout.split("\n"):
            low = line.lower()

            # Immutable / constant state variables
            if "immutable" in low or "constant" in low:
                m = re.search(r"(\w+)\s+\(", line)
                if m:
                    var = m.group(1)
                    invariants.append({
                        "type":     "immutable",
                        "variable": var,
                        "property": f"{var} never changes after construction",
                        "severity": "info",
                    })

            # Access-control modifiers
            if "onlyowner" in low or "onlyrole" in low or "onlyadmin" in low:
                m = re.search(r"(\w+)\s*\(", line)
                if m:
                    func = m.group(1)
                    invariants.append({
                        "type":     "access_control",
                        "function": func,
                        "property": f"only authorized callers may invoke {func}",
                        "severity": "high",
                    })

        # ── 2. reentrancy detector ────────────────────────────────────
        r2 = subprocess.run(
            ["slither", solidity_file, "--detect", "reentrancy-eth,reentrancy-no-eth"],
            capture_output=True, text=True, timeout=60
        )
        raw_outputs.append(r2.stdout)

        for line in r2.stdout.split("\n"):
            if "reentrancy" in line.lower():
                m = re.search(r"(\w+)\.", line)
                func = m.group(1) if m else "unknown"
                invariants.append({
                    "type":     "reentrancy",
                    "function": func,
                    "property": f"no reentrancy in {func}",
                    "severity": "critical",
                })

        # ── 3. integer overflow / underflow ───────────────────────────
        r3 = subprocess.run(
            ["slither", solidity_file, "--detect", "tautology,divide-before-multiply"],
            capture_output=True, text=True, timeout=60
        )
        raw_outputs.append(r3.stdout)

        for line in r3.stdout.split("\n"):
            if "overflow" in line.lower() or "underflow" in line.lower():
                m = re.search(r"(\w+)\s", line)
                var = m.group(1) if m else "value"
                invariants.append({
                    "type":     "overflow",
                    "variable": var,
                    "property": f"no overflow/underflow on {var}",
                    "severity": "high",
                })

        return {
            "source":     "Slither",
            "file":       solidity_file,
            "invariants": invariants,
            "raw_output": "\n".join(raw_outputs)[:4000],
        }

    # ── LTL generation ────────────────────────────────────────────────

    def generate_ltl_from_slither(self, solidity_file: str) -> str:
        """
        Convert Slither findings into Promela LTL properties that can be
        pasted directly into the Specifications & LTL editor tab.
        """
        findings = self.extract_invariants(solidity_file)
        if "error" in findings:
            return f"/* Slither error: {findings['error']} */"

        lines: list[str] = [
            f"/* LTL properties generated by Slither from {os.path.basename(solidity_file)} */",
            "",
        ]

        for inv in findings.get("invariants", []):
            t = inv["type"]

            if t == "access_control":
                func = inv["function"]
                lines.append(
                    f"ltl {func}_auth "
                    f"{{ [] (called_{func} -> authorized_caller) }}"
                )

            elif t == "immutable":
                var = inv["variable"]
                lines.append(
                    f"ltl {var}_constant "
                    f"{{ [] ({var} == initial_{var}) }}"
                )

            elif t == "reentrancy":
                func = inv["function"]
                lines.append(
                    f"ltl {func}_no_reentry "
                    f"{{ [] !(lock && calling_{func}) }}"
                )

            elif t == "overflow":
                var = inv.get("variable", "value")
                lines.append(
                    f"ltl {var}_no_overflow "
                    f"{{ [] ({var} >= 0 && {var} <= MAX_UINT) }}"
                )

        if len(lines) <= 2:
            lines.append("/* No Slither findings — model is clean */")
            lines.append("ltl safety_default { [] (true) }")

        return "\n".join(lines)

    # ── Certora rule generation ───────────────────────────────────────

    def generate_certora_rules(self, solidity_file: str) -> str:
        """
        Convert Slither findings into Certora Prover rules (.spec format).
        """
        findings = self.extract_invariants(solidity_file)
        if "error" in findings:
            return f"/* Slither error: {findings['error']} */"

        contract = os.path.splitext(os.path.basename(solidity_file))[0]
        lines: list[str] = [
            f"/* Certora rules generated by Slither from {contract} */",
            "",
            "methods {",
            "    // Add your contract's external functions here",
            "}",
            "",
        ]

        for inv in findings.get("invariants", []):
            t = inv["type"]

            if t == "access_control":
                func = inv["function"]
                lines += [
                    f"// Rule: only authorized callers may invoke {func}",
                    f"rule {func}_access_control(method f) {{",
                    f"    calldataarg args;",
                    f"    f(e, args);",
                    f"    assert msg.sender == owner(),",
                    f'        "ACCESS CONTROL: unauthorized call to {func}";',
                    "}",
                    "",
                ]

            elif t == "reentrancy":
                func = inv["function"]
                lines += [
                    f"// Rule: no reentrancy in {func}",
                    f"rule {func}_no_reentrancy() {{",
                    f"    require !isLocked();",
                    f"    {func}@withrevert(e);",
                    f"    assert !isLocked(),",
                    f'        "REENTRANCY: lock not released after {func}";',
                    "}",
                    "",
                ]

            elif t == "immutable":
                var = inv["variable"]
                lines += [
                    f"// Rule: {var} is immutable after construction",
                    f"invariant {var}_immutable()",
                    f"    {var}() == initial_{var}()",
                    f'    filtered {{ f -> f.selector != sig:constructor() }}',
                    "",
                ]

        return "\n".join(lines)

    # ── summary report ────────────────────────────────────────────────

    def generate_summary(self, solidity_file: str) -> str:
        """Human-readable summary of all Slither findings."""
        findings = self.extract_invariants(solidity_file)
        if "error" in findings:
            return f"Error: {findings['error']}"

        invs = findings.get("invariants", [])
        lines = [
            "=" * 60,
            "SLITHER ANALYSIS SUMMARY",
            "=" * 60,
            f"File: {solidity_file}",
            f"Total findings: {len(invs)}",
            "",
        ]

        by_severity: dict[str, list] = {"critical": [], "high": [], "info": []}
        for inv in invs:
            sev = inv.get("severity", "info")
            by_severity.setdefault(sev, []).append(inv)

        for sev in ("critical", "high", "info"):
            group = by_severity.get(sev, [])
            if not group:
                continue
            lines.append(f"[{sev.upper()}]")
            for inv in group:
                lines.append(f"  • {inv['property']}")
            lines.append("")

        if not invs:
            lines.append("No issues found — contract looks clean.")

        return "\n".join(lines)


# ── convenience function ──────────────────────────────────────────────

def analyze_and_generate(
    solidity_file: str,
    output_format: str = "ltl",
) -> str:
    """
    One-shot helper used by the desktop app.

    *output_format* can be ``"ltl"``, ``"certora"``, or ``"summary"``.
    """
    extractor = SlitherSpecExtractor()
    if output_format == "certora":
        return extractor.generate_certora_rules(solidity_file)
    if output_format == "summary":
        return extractor.generate_summary(solidity_file)
    return extractor.generate_ltl_from_slither(solidity_file)
