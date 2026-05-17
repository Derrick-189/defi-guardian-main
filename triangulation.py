"""
DeFi Guardian — verification triangulation.

Runs overlapping checks (SPIN on translated Promela, Prusti / Kani / Creusot on Rust)
and summarizes agreement. Optional Verus and AENEAS when installed.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from typing import Any


class VerificationTriangulator:
    """Run multiple verifiers on related artifacts and compare outcomes."""

    def __init__(self, project_dir: str | None = None):
        self.project_dir = project_dir or os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def _cmd_ok(cmd: list[str], timeout: float = 5.0) -> bool:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def check_tool_availability(self) -> dict[str, bool]:
        """Probe binaries used by :meth:`triangulate_property`."""
        return {
            "spin": self._cmd_ok(["spin", "-V"], timeout=2),
            "kani": self._cmd_ok(["cargo", "kani", "--version"], timeout=8),
            "prusti": self._cmd_ok(["prusti-rustc", "--version"], timeout=5),
            "creusot": self._cmd_ok(["cargo", "creusot", "--help"], timeout=8),
            "verus": self._cmd_ok(["verus", "--version"], timeout=5),
            "aeneas": self._cmd_ok(["aeneas", "--version"], timeout=5),
        }

    def triangulate_property(
        self,
        rust_file: str,
        property_name: str,
        property_formula: str | None = None,
    ) -> dict[str, Any]:
        """
        Run every available tool; return structured results plus consensus heuristics.

        ``property_name`` / ``property_formula`` are recorded for reporting only unless
        a backend is later wired to consume them.
        """
        results: dict[str, Any] = {
            "property": property_name,
            "formula": property_formula,
            "timestamp": datetime.now().isoformat(),
            "tools": {},
            "consensus": None,
            "confidence": 0.0,
        }

        tools_available = self.check_tool_availability()

        if tools_available.get("spin"):
            results["tools"]["spin"] = self._verify_with_spin(rust_file, property_name)

        rust_code = ""
        if any(
            tools_available.get(t)
            for t in ("kani", "prusti", "creusot")
        ):
            try:
                with open(rust_file, "r", encoding="utf-8") as f:
                    rust_code = f.read()
            except OSError as e:
                err = {"success": False, "error": str(e), "tool": "Rust suite"}
                for t in ("prusti", "kani", "creusot"):
                    if tools_available.get(t):
                        results["tools"][t] = dict(err, tool=t)

        if rust_code:
            from rust_verifiers import RustVerifier

            verifier = RustVerifier()
            annotated = verifier.analyze_and_annotate(rust_code)

            if tools_available.get("prusti"):
                t0 = time.perf_counter()
                r = verifier.verify_with_prusti(annotated, skip_analyze=True)
                results["tools"]["prusti"] = self._pack_rust_tool(
                    "Prusti (static verifier)", r, time.perf_counter() - t0
                )

            if tools_available.get("kani"):
                t0 = time.perf_counter()
                kani_src = verifier._add_kani_harness(annotated)
                r = verifier.verify_with_kani(kani_src)
                results["tools"]["kani"] = self._pack_rust_tool(
                    "Kani (bounded model checking)", r, time.perf_counter() - t0
                )

            if tools_available.get("creusot"):
                t0 = time.perf_counter()
                r = verifier.verify_with_creusot(annotated)
                results["tools"]["creusot"] = self._pack_rust_tool(
                    "Creusot (deductive verification)", r, time.perf_counter() - t0
                )

        if tools_available.get("verus"):
            results["tools"]["verus"] = self._verify_with_verus(rust_file, property_name)

        if tools_available.get("aeneas"):
            results["tools"]["aeneas_coq"] = self._verify_with_aeneas(
                rust_file, property_name
            )

        results["consensus"] = self._compute_consensus(results["tools"])
        results["confidence"] = self._compute_confidence(results["tools"])

        return results

    @staticmethod
    def _pack_rust_tool(label: str, r: dict, elapsed: float) -> dict[str, Any]:
        skipped = bool(r.get("skipped"))
        ok = bool(r.get("success")) and not skipped
        return {
            "success": ok,
            "skipped": skipped,
            "time": elapsed,
            "output": (r.get("output") or "")[:500],
            "errors": (r.get("errors") or r.get("error") or "")[:500],
            "tool": label,
        }

    def _verify_with_spin(self, rust_file: str, property_name: str) -> dict[str, Any]:
        try:
            from translator import DeFiTranslator

            with open(rust_file, "r", encoding="utf-8") as f:
                code = f.read()

            pml = DeFiTranslator.translate_rust(code)
            pml_file = os.path.join(self.project_dir, "temp_model.pml")
            with open(pml_file, "w", encoding="utf-8") as f:
                f.write(pml)

            t0 = time.perf_counter()
            r_spin = subprocess.run(
                ["spin", "-a", "temp_model.pml"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r_spin.returncode != 0:
                return {
                    "success": False,
                    "time": time.perf_counter() - t0,
                    "output": (r_spin.stdout or "")[:500],
                    "errors": (r_spin.stderr or r_spin.stdout or "")[:500],
                    "tool": "SPIN (explicit-state)",
                }

            r_gcc = subprocess.run(
                ["gcc", "-o", "pan", "pan.c"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r_gcc.returncode != 0:
                return {
                    "success": False,
                    "time": time.perf_counter() - t0,
                    "output": (r_gcc.stdout or "")[:500],
                    "errors": (r_gcc.stderr or "")[:500],
                    "tool": "SPIN (explicit-state)",
                }

            pan_path = "./pan"
            if os.name == "nt":
                pan_path = "pan.exe"
            
            # Ensure path is absolute if needed, or relative to project_dir
            r_pan = subprocess.run(
                [pan_path, "-a"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            elapsed = time.perf_counter() - t0
            out = r_pan.stdout or ""
            success = r_pan.returncode == 0 and "errors: 0" in out

            return {
                "success": success,
                "time": elapsed,
                "output": out[:500],
                "errors": (r_pan.stderr or "")[:500],
                "tool": "SPIN (explicit-state)",
            }
        except Exception as e:
            return {"success": False, "error": str(e), "tool": "SPIN"}
        finally:
            for name in ("pan", "pan.c", "pan.b", "temp_model.pml"):
                path = os.path.join(self.project_dir, name)
                if os.path.isfile(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def _verify_with_verus(self, rust_file: str, property_name: str) -> dict[str, Any]:
        try:
            from verus_integration import VerusIntegration

            t0 = time.perf_counter()
            r = VerusIntegration().verify_with_verus(rust_file)
            return {
                "success": bool(r.get("success")),
                "time": time.perf_counter() - t0,
                "output": (r.get("output") or "")[:500],
                "errors": (r.get("errors") or "")[:500],
                "tool": "Verus (SMT)",
            }
        except Exception as e:
            return {"success": False, "error": str(e), "tool": "Verus"}

    def _verify_with_aeneas(self, rust_file: str, property_name: str) -> dict[str, Any]:
        try:
            from aeneas_integration import AeneasTranslator

            t0 = time.perf_counter()
            r = AeneasTranslator().translate_rust_to_coq(rust_file)
            elapsed = time.perf_counter() - t0
            return {
                "success": bool(r.get("success")),
                "time": elapsed,
                "output": (r.get("output") or r.get("coq_code") or "")[:500],
                "errors": (r.get("error") or "")[:500],
                "tool": "AENEAS → Coq",
            }
        except Exception as e:
            return {"success": False, "error": str(e), "tool": "AENEAS"}

    def _compute_consensus(self, tool_results: dict[str, Any]) -> str:
        if not tool_results:
            return "NO_TOOLS_AVAILABLE"

        decisions: list[bool] = []
        for _tool, result in tool_results.items():
            if not isinstance(result, dict):
                continue
            if result.get("skipped"):
                continue
            decisions.append(bool(result.get("success")))

        if not decisions:
            return "NO_TOOLS_AVAILABLE"

        total = len(decisions)
        passed = sum(1 for x in decisions if x)

        if passed == total:
            return "FULL_CONSENSUS"
        if passed > total / 2:
            return f"PARTIAL_CONSENSUS ({passed}/{total})"
        if passed == 0:
            return f"NO_CONSENSUS ({passed}/{total})"
        return f"NO_CONSENSUS ({passed}/{total})"

    def _compute_confidence(self, tool_results: dict[str, Any]) -> float:
        weights = {
            "spin": 0.20,
            "creusot": 0.22,
            "prusti": 0.18,
            "kani": 0.15,
            "verus": 0.15,
            "aeneas_coq": 0.10,
        }

        score = 0.0
        total_weight = 0.0

        for tool, weight in weights.items():
            if tool not in tool_results:
                continue
            r = tool_results[tool]
            if not isinstance(r, dict) or r.get("skipped"):
                continue
            total_weight += weight
            if r.get("success"):
                score += weight

        if total_weight == 0:
            return 0.0
        return (score / total_weight) * 100.0

    def generate_report(self, results: dict[str, Any]) -> str:
        lines = [
            "=" * 70,
            "TRIANGULATION REPORT",
            "=" * 70,
            f"Property: {results.get('property', 'N/A')}",
            f"Formula: {results.get('formula', 'N/A')}",
            f"Timestamp: {results.get('timestamp', 'N/A')}",
            "",
            "-" * 70,
            "TOOL RESULTS:",
            "-" * 70,
        ]

        for tool, result in (results.get("tools") or {}).items():
            if not isinstance(result, dict):
                continue
            if result.get("skipped"):
                status = "⏭️ SKIP"
            else:
                status = "✅ PASS" if result.get("success") else "❌ FAIL"
            tstr = f"{result.get('time', 0):.2f}s" if result.get("time") is not None else "N/A"
            name = result.get("tool", tool.upper())
            lines.append(f"  {name}: {status} ({tstr})")

        lines.extend(
            [
                "",
                "-" * 70,
                "CONSENSUS ANALYSIS:",
                "-" * 70,
                f"  Consensus: {results.get('consensus')}",
                f"  Confidence score: {results.get('confidence', 0.0):.1f}%",
                "",
                "=" * 70,
            ]
        )
        return "\n".join(lines)

    def save_report(self, results: dict[str, Any], filename: str | None = None) -> str:
        if filename is None:
            filename = f"triangulation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        report_path = os.path.join(self.project_dir, filename)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(self.generate_report(results))

        json_path = os.path.splitext(report_path)[0] + ".json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        return report_path
