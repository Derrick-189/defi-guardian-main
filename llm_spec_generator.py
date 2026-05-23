"""
DeFi Guardian — LLM-assisted specification generator.

Uses pattern matching offline; optionally calls an OpenAI-compatible API when
``use_llm`` is true and a key is set (``OPENAI_API_KEY`` or constructor).
"""

from __future__ import annotations

import os
import re
from typing import Any


class LLMSpecGenerator:
    """Generate formal-style specs from Rust text (patterns + optional LLM)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        use_llm: bool = False,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.use_llm = bool(use_llm and self.api_key)

        self.patterns: dict[str, dict[str, Any]] = {
            "checked_add": {
                "requires": ["amount <= u64::MAX - self.{field}"],
                "ensures": ["self.{field} == old(self.{field}) + amount"],
            },
            "checked_sub": {
                "requires": ["amount <= self.{field}"],
                "ensures": ["self.{field} == old(self.{field}) - amount"],
            },
            "checked_mul": {
                "requires": [],
                "ensures": ["/* checked_mul: no overflow on Some(_) path */"],
            },
            "require!": {"extract": True},
            "assert!": {"extract": True},
        }

        self.function_semantics: dict[str, dict[str, list[str]]] = {
            "deposit": {
                "requires": ["amount > 0"],
                "ensures": ["self.balance == old(self.balance) + amount"],
            },
            "withdraw": {
                "requires": ["amount > 0", "amount <= self.balance"],
                "ensures": ["self.balance == old(self.balance) - amount"],
            },
            "borrow": {
                "requires": [
                    "amount > 0",
                    "self.collateral_value() >= self.debt + amount",
                ],
                "ensures": ["self.debt == old(self.debt) + amount"],
            },
            "repay": {
                "requires": ["amount > 0", "amount <= self.debt"],
                "ensures": ["self.debt == old(self.debt) - amount"],
            },
            "liquidate": {
                "requires": ["self.health_factor() < 100"],
                "ensures": ["self.debt == 0"],
            },
            "transfer": {
                "requires": ["amount <= self.balance"],
                "ensures": ["self.balance == old(self.balance) - amount"],
            },
        }

    @staticmethod
    def _infer_field_for_checked_ops(rust_function: str) -> str:
        """Guess which struct field is updated by checked_* on ``self``."""
        t = rust_function.lower()
        if "debt" in t and ("checked_add" in t or "checked_sub" in t):
            return "debt"
        if "balance" in t:
            return "balance"
        if "collateral" in t:
            return "collateral"
        return "balance"

    def generate_specs_from_code(
        self, rust_function: str, function_name: str | None = None
    ) -> dict[str, list[str]]:
        """
        Analyze a Rust function snippet and suggest requires / ensures / invariants.

        Prusti ``#[requires]/#[ensures]`` need valid Rust boolean expressions; some
        entries (e.g. checked_mul note) may need manual editing.
        """
        specs: dict[str, list[str]] = {
            "requires": [],
            "ensures": [],
            "invariants": [],
        }

        assertions = re.findall(
            r"(?:require|assert)!\s*\(([^)]+)\)", rust_function, re.DOTALL
        )
        for assertion in assertions:
            clean = " ".join(assertion.split())
            if clean and clean not in specs["requires"]:
                specs["requires"].append(clean)

        field = self._infer_field_for_checked_ops(rust_function)
        for pattern, rules in self.patterns.items():
            if pattern not in rust_function:
                continue
            if rules.get("extract"):
                continue
            for req in rules.get("requires", []):
                s = req.format(field=field)
                if s and s not in specs["requires"]:
                    specs["requires"].append(s)
            for ens in rules.get("ensures", []):
                s = ens.format(field=field)
                if s.startswith("/*"):
                    if s not in specs["ensures"]:
                        specs["ensures"].append(s)
                elif s and s not in specs["ensures"]:
                    specs["ensures"].append(s)

        if function_name:
            fl = function_name.lower()
            for key, semantics in self.function_semantics.items():
                if key not in fl:
                    continue
                for req in semantics.get("requires", []):
                    if req not in specs["requires"]:
                        specs["requires"].append(req)
                for ens in semantics.get("ensures", []):
                    if ens not in specs["ensures"]:
                        specs["ensures"].append(ens)

        low = rust_function.lower()
        if "collateral" in low and "debt" in low:
            inv = "self.collateral * self.price >= self.debt"
            if inv not in specs["invariants"]:
                specs["invariants"].append(inv)

        if "lock" in low or "reentrancy" in low:
            inv = "!self.lock || amount == 0"
            if inv not in specs["invariants"]:
                specs["invariants"].append(inv)

        return specs

    def generate_prusti_annotations(
        self, rust_function: str, function_name: str | None = None
    ) -> str:
        """Build ``#[requires]`` / ``#[ensures]`` lines (skip comment-only ensures)."""
        specs = self.generate_specs_from_code(rust_function, function_name)
        lines: list[str] = []
        for req in specs["requires"]:
            lines.append(f"#[requires({req})]")
        for ens in specs["ensures"]:
            if ens.strip().startswith("/*"):
                continue
            lines.append(f"#[ensures({ens})]")
        return "\n".join(lines)

    def generate_kani_harness(self, rust_code: str) -> str:
        """Append-style Kani smoke block (first few ``pub fn`` names as comments)."""
        functions = re.findall(r"(?:pub\s+)?fn\s+(\w+)\s*\(", rust_code)
        lines = [
            "",
            "#[cfg(kani)]",
            "#[kani::proof]",
            "fn verify_properties() {",
        ]
        for func in functions[:3]:
            lines.append(f"    // sketch: exercise `{func}`")
            lines.append("    let amount: u64 = kani::any();")
            lines.append("    kani::assume(amount > 0 && amount < 1_000_000);")
        lines.append("    kani::assert(true);")
        lines.append("}")
        lines.append("")
        return "\n".join(lines)

    def generate_ltl_from_description(self, description: str) -> str:
        """Map natural language to Promela-style LTL skeletons (placeholders)."""
        desc = (description or "").strip()
        if not desc:
            return "[] (true)"

        patterns: list[tuple[str, str]] = [
            (r"never.*happen|always.*true|must.*hold", "[] (condition)"),
            (r"eventually.*will|must.*happen", "<> (condition)"),
            (r"if.*then.*eventually", "[] (trigger -> <> response)"),
            (r"\buntil\b", "(condition1 U condition2)"),
        ]
        for regex, template in patterns:
            if re.search(regex, desc, re.IGNORECASE):
                return (
                    template.replace("{condition}", "condition")
                    .replace("{trigger}", "trigger")
                    .replace("{response}", "response")
                    .replace("{condition1}", "condition1")
                    .replace("{condition2}", "condition2")
                )
        return "[] (true)"

    def call_llm(self, prompt: str) -> str | None:
        """Optional LLM call; returns ``None`` if disabled or on failure."""
        if not self.use_llm or not self.api_key:
            return None

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            r = client.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a formal verification assistant. "
                            "Output concise Rust boolean expressions for "
                            "Prusti requires/ensures only, no markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=500,
            )
            return (r.choices[0].message.content or "").strip() or None
        except ImportError:
            return None
        except Exception:
            return None


def specs_for_rust_verifier(func_name: str, specs: dict[str, list[str]]) -> dict[str, Any]:
    """Build a ``properties`` dict for :meth:`RustVerifier.analyze_and_annotate`."""
    return {
        "functions": {
            func_name: {
                "requires": list(specs.get("requires") or []),
                "ensures": list(specs.get("ensures") or []),
            }
        }
    }
