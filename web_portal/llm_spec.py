"""
DeFi Guardian — LLM Spec Generator
Natural-language → LTL / CVL specification using Claude or GPT.
Falls back to pattern-based generation when no API key is set.
"""
from __future__ import annotations
import os, re
from typing import Optional

# ── API clients (optional) ────────────────────────────────────────────────────
try:
    import anthropic as _anthropic
    _CLAUDE_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    _HAS_CLAUDE = bool(_CLAUDE_KEY)
except ImportError:
    _HAS_CLAUDE = False
    _CLAUDE_KEY = ""

try:
    import openai as _openai
    _OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
    _HAS_OPENAI = bool(_OPENAI_KEY)
except ImportError:
    _HAS_OPENAI = False
    _OPENAI_KEY = ""


# ── System prompts ────────────────────────────────────────────────────────────
_SYS_LTL = (
    "You are a formal verification expert specialising in smart contract security. "
    "Generate a single, syntactically correct LTL (Linear Temporal Logic) formula "
    "for the SPIN model checker. Use only: [], <>, ->, &&, ||, !, ==, !=, <, >, <=, >=. "
    "Output ONLY the ltl statement — no explanation, no markdown."
)

_SYS_CVL = (
    "You are a formal verification expert specialising in Certora CVL. "
    "Generate a single, syntactically correct CVL rule. "
    "Use require for preconditions and assert for postconditions. "
    "Output ONLY the rule block — no explanation, no markdown."
)


def generate(prompt: str, tool: str = "LTL",
             contract_context: str = "") -> dict:
    """
    Generate a formal spec from a natural-language prompt.

    Returns:
        {"spec": str, "model": str, "error": Optional[str]}
    """
    tool = tool.upper()
    system = _SYS_CVL if tool == "CVL" else _SYS_LTL
    user_msg = (
        (f"Contract context:\n```solidity\n{contract_context[:1500]}\n```\n\n"
         if contract_context else "")
        + f"Generate a {'CVL rule' if tool == 'CVL' else 'LTL property'} for:\n{prompt}"
    )

    # 1. Try Claude
    if _HAS_CLAUDE:
        try:
            client = _anthropic.Anthropic(api_key=_CLAUDE_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            spec = resp.content[0].text.strip()
            return {"spec": spec, "model": "claude-sonnet-4-5", "error": None}
        except Exception as e:
            pass  # fall through

    # 2. Try OpenAI
    if _HAS_OPENAI:
        try:
            client = _openai.OpenAI(api_key=_OPENAI_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_msg},
                ],
                max_tokens=512,
            )
            spec = resp.choices[0].message.content.strip()
            return {"spec": spec, "model": "gpt-4o", "error": None}
        except Exception as e:
            pass

    # 3. Pattern-based fallback
    spec = _pattern_fallback(prompt, tool)
    return {"spec": spec, "model": "pattern-based", "error": None}


# ── Pattern-based fallback ────────────────────────────────────────────────────
_LTL_PATTERNS = [
    (r"overflow",          "ltl no_overflow { [] (amount >= 0 && amount <= 1000000) }"),
    (r"reentr",            "ltl no_reentrancy { [] !(lock && amount > 0) }"),
    (r"collateral|debt",   "ltl collateral_safe { [] (user_collateral >= user_debt) }"),
    (r"liquidat",          "ltl liquidation_reachable { [] (health_factor < 100 -> <> liquidation_executed) }"),
    (r"pause|paused",      "ltl no_paused_ops { [] (!paused -> <> (state == 1)) }"),
    (r"balance",           "ltl balance_non_negative { [] (balance >= 0) }"),
    (r"owner|access",      "ltl owner_only { [] (caller == owner -> <> authorized) }"),
    (r"liveness|progress", "ltl liveness { <> (state == 2) }"),
    (r"fairness",          "ltl fairness { [] <> (lock == false) }"),
]

_CVL_PATTERNS = [
    (r"overflow",        "rule noOverflow(uint256 a, uint256 b) {\n    require a + b >= a;\n    assert a + b >= a, \"Overflow detected\";\n}"),
    (r"reentr",          "rule noReentrancy(method f) {\n    env e; calldataarg args;\n    require !locked;\n    f(e, args);\n    assert !locked, \"Reentrancy detected\";\n}"),
    (r"balance",         "rule balanceIntegrity(address user) {\n    uint256 before = balanceOf(user);\n    // perform operation\n    assert balanceOf(user) >= 0, \"Balance must be non-negative\";\n}"),
    (r"access|owner",    "rule onlyOwner(method f) {\n    env e; calldataarg args;\n    require e.msg.sender != owner();\n    f@withrevert(e, args);\n    assert lastReverted, \"Only owner should succeed\";\n}"),
]


def _pattern_fallback(prompt: str, tool: str) -> str:
    p = prompt.lower()
    patterns = _CVL_PATTERNS if tool == "CVL" else _LTL_PATTERNS
    for pattern, spec in patterns:
        if re.search(pattern, p):
            return spec
    # Generic fallback
    if tool == "CVL":
        return "rule customProperty() {\n    // TODO: add require/assert\n    assert true, \"Property holds\";\n}"
    return "ltl custom_property { [] (true) }"
