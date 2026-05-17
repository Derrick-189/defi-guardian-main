"""
DeFi Guardian — Verification Simulator
Produces realistic deterministic output for all 8 tools when binaries are absent.
Auto-switches to real binaries when detected on PATH.
"""
from __future__ import annotations
import os, re, json, shutil, subprocess, time, uuid, hashlib, sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent.parent
# Ensure project root is on sys.path for imports (translator, etc.)
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# ── Binary detection ──────────────────────────────────────────────────────────
TOOL_CMDS = {
    "SPIN":    "spin",
    "COQ":     "coqc",
    "LEAN":    "lean",
    "CERTORA": "certoraRun",
    "KANI":    "cargo-kani",
    "PRUSTI":  "cargo-prusti",
    "CREUSOT": "cargo-creusot",
    "VERUS":   "verus",
}

def tool_available(tool: str) -> bool:
    return shutil.which(TOOL_CMDS.get(tool.upper(), "")) is not None


# ── Simulated outputs ─────────────────────────────────────────────────────────

_LTL_PROPS = [
    ("safety_no_overflow",      "[] (amount >= 0 && amount <= 1000000)",          True),
    ("safety_reentrancy",       "[] !(lock && amount > 100)",                     True),
    ("liveness_progress",       "<> (state == 2)",                                True),
    ("invariant_collateral",    "[] (user_collateral >= user_debt)",              True),
    ("response_price_drop",     "[] (price_eth < 50 -> <> (health_factor < 150))", True),
    ("stability",               "[] (lock == false -> <> (amount > 0 && health_factor > 200))", False),
    ("fairness",                "[] <> (lock == false)",                          True),
    ("reachability_liquidation","[] (health_factor < 100 -> <> (liquidation_executed == 1))", False),
]

def _parse_spin_ltl(output: str) -> list:
    """Extract LTL property results from SPIN output."""
    ltl_results = []
    pattern = re.compile(r"--- LTL (\w+) ---.*?errors:\s*(\d+)", re.DOTALL)
    for m in pattern.finditer(output):
        name = m.group(1)
        errors = int(m.group(2))
        ltl_results.append({
            "name": name,
            "success": errors == 0,
            "formula": "",
            "errors": errors,
        })
    return ltl_results


def _spin_sim(contract_name: str, seed: int = 0) -> dict:
    """Simulate SPIN output deterministically based on contract name."""
    h = int(hashlib.md5(contract_name.encode()).hexdigest(), 16)
    fail_mask = (h >> seed) & 0xFF   # which props fail

    ltl_results = []
    output_lines = []
    errors_total = 0

    for i, (name, formula, default_pass) in enumerate(_LTL_PROPS):
        # Deterministic pass/fail: use bit from hash
        passes = default_pass if (fail_mask >> i) & 1 == 0 else not default_pass
        errors = 0 if passes else 1
        errors_total += errors

        output_lines.append(f"\n--- LTL {name} ---")
        output_lines.append(f"pan: ltl formula {name}")
        output_lines.append("(Spin Version 6.5.2 -- 6 December 2019)")
        output_lines.append("\t+ Partial Order Reduction")
        output_lines.append(f"\nState-vector 52 byte, depth reached 15, errors: {errors}")
        output_lines.append("        7 states, stored")
        output_lines.append("        1 states, matched")
        output_lines.append("        8 transitions (= stored+matched)")
        if not passes:
            output_lines.append(f"pan:1: acceptance cycle (at depth 14)")
            output_lines.append(f"pan: wrote translated_output.pml.trail")
        output_lines.append("pan: elapsed time 0 seconds")

        ltl_results.append({
            "name": name, "success": passes,
            "formula": formula, "errors": errors,
        })

    return {
        "output": "\n".join(output_lines),
        "ltl_results": ltl_results,
        "states_stored": 7,
        "transitions": 8,
        "depth": 15,
        "errors_count": errors_total,
        "success": errors_total == 0,
    }


def _coq_sim(contract_name: str) -> dict:
    theorems = [
        ("all_values_non_negative", True),
        ("ltl_safety_no_overflow_holds", True),
        ("ltl_safety_reentrancy_holds", True),
        ("ltl_liveness_progress_holds", False),   # Admitted
        ("ltl_invariant_collateral_holds", True),
        ("ltl_response_price_drop_holds", False),  # Admitted
        ("ltl_stability_holds", False),            # Admitted
        ("ltl_fairness_holds", True),
        ("ltl_reachability_liquidation_holds", False),  # Admitted
    ]
    lines = [f"(* Coq verification for {contract_name} *)"]
    for name, proved in theorems:
        lines.append(f"Theorem {name}: ... {'Qed.' if proved else 'Admitted.'}")
    qed_count = sum(1 for _, p in theorems if p)
    admitted = len(theorems) - qed_count
    lines.append(f"\n(* Summary: {qed_count} Qed, {admitted} Admitted *)")
    return {
        "output": "\n".join(lines),
        "theorems": [{"name": n, "proved": p} for n, p in theorems],
        "success": admitted == 0,
        "qed_count": qed_count,
        "admitted_count": admitted,
    }


def _lean_sim(contract_name: str) -> dict:
    theorems = [
        ("safety_no_overflow", True),
        ("reentrancy_guard", True),
        ("collateral_invariant", True),
        ("liveness_progress", False),
    ]
    lines = [f"-- Lean 4 verification for {contract_name}"]
    for name, proved in theorems:
        lines.append(f"theorem {name} : ... := {'by simp' if proved else 'by sorry'}")
    sorry_count = sum(1 for _, p in theorems if not p)
    return {
        "output": "\n".join(lines),
        "theorems": [{"name": n, "proved": p} for n, p in theorems],
        "success": sorry_count == 0,
        "sorry_count": sorry_count,
    }


def _certora_sim(contract_name: str) -> dict:
    rules = [
        ("constructorSanity", True),
        ("noUnexpectedRevert", True),
        ("balanceIntegrity", True),
        ("accessControl", False),
    ]
    lines = [f"Certora Prover — {contract_name}"]
    for name, passed in rules:
        lines.append(f"  Rule {name}: {'[PASS]' if passed else '[FAIL] counterexample found'}")
    fail_count = sum(1 for _, p in rules if not p)
    return {
        "output": "\n".join(lines),
        "rules": [{"name": n, "passed": p} for n, p in rules],
        "success": fail_count == 0,
        "fail_count": fail_count,
    }


def _kani_sim(contract_name: str) -> dict:
    checks = [
        ("no_integer_overflow", True),
        ("no_panic", True),
        ("bounds_check", True),
    ]
    lines = [f"Kani Bounded Model Checker — {contract_name}"]
    for name, sat in checks:
        lines.append(f"  Check: {name} — {'SATISFIED' if sat else 'FAILED'}")
    lines.append(f"\nVERIFICATION:- {'SUCCESSFUL' if all(s for _, s in checks) else 'FAILED'}")
    return {
        "output": "\n".join(lines),
        "checks": [{"name": n, "satisfied": s} for n, s in checks],
        "success": all(s for _, s in checks),
    }


def _prusti_sim(contract_name: str) -> dict:
    return {
        "output": f"Prusti — {contract_name}\nVerification successful\n[INFO] All postconditions hold.",
        "success": True,
    }


def _creusot_sim(contract_name: str) -> dict:
    return {
        "output": f"Creusot — {contract_name}\nWhy3 session: all goals proved.",
        "success": True,
    }


def _verus_sim(contract_name: str) -> dict:
    return {
        "output": f"Verus — {contract_name}\nverification results:: 3 verified, 0 errors",
        "success": True,
    }


_SIM_MAP = {
    "SPIN":    _spin_sim,
    "COQ":     _coq_sim,
    "LEAN":    _lean_sim,
    "CERTORA": _certora_sim,
    "KANI":    _kani_sim,
    "PRUSTI":  _prusti_sim,
    "CREUSOT": _creusot_sim,
    "VERUS":   _verus_sim,
}


def simulate(tool: str, contract_name: str = "Contract") -> dict:
    """Return simulated verification result for the given tool."""
    fn = _SIM_MAP.get(tool.upper())
    if fn:
        return fn(contract_name)
    return {"output": f"[{tool}] No simulator available.", "success": False}


def run_or_simulate(tool: str, contract_name: str = "Contract",
                    source_path: str = "", specs: str = "") -> dict:
    """
    Try real binary first; fall back to simulator.
    For SPIN, inject custom specs if provided.
    Returns unified dict with keys: output, success, tool, simulated, log_path, trace_path.
    """
    tool_up = tool.upper()
    result = {"tool": tool_up, "simulated": True, "contract": contract_name}

    if tool_available(tool_up) and source_path and os.path.exists(source_path):
        try:
            result.update(_run_real(tool_up, source_path, specs))
            result["simulated"] = False
            return result
        except Exception as e:
            result["real_error"] = str(e)

    # Fall back to simulator
    result.update(simulate(tool_up, contract_name))

    # For simulated runs, also create a dummy log file so audit record can reference it
    if result.get("simulated", True):
        try:
            log_dir = PROJECT_DIR / "logs" / "simulated"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_path = str(log_dir / f"{tool_up.lower()}_{ts}.log")
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(result.get('output', ''))
            result['log_path'] = log_path
            result['trace_path'] = ''
        except Exception:
            pass

    return result


def _run_real(tool: str, source_path: str, specs: str = "") -> dict:
    """Attempt to run the real binary. Raises on failure."""
    import subprocess
    import shutil
    from pathlib import Path
    from datetime import datetime

    PROJECT_DIR = Path(__file__).parent.parent
    LOGS_DIR   = PROJECT_DIR / "logs" / "spin"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR = PROJECT_DIR / "generated" / "models"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    cmd_map = {
        "SPIN":    ["spin", "-a", source_path],
        "COQ":     ["coqc", source_path],
        "LEAN":    ["lean", source_path],
        "CERTORA": ["certoraRun", source_path],
        "KANI":    ["cargo", "kani", "--harness", "verify"],
        "PRUSTI":  ["cargo", "prusti"],
        "CREUSOT": ["cargo", "creusot"],
        "VERUS":   ["verus", source_path],
    }
    cmd = cmd_map.get(tool, [])
    if not cmd:
        raise ValueError(f"No command for {tool}")

    if tool == "SPIN":
        src_path = Path(source_path)
        base_content = ""
        base_file    = None

        # Step A: obtain Promela model
        if src_path.suffix in ('.sol', '.rs'):
            try:
                from translator import VerifiedTranslator, DeFiTranslator
                with open(src_path, 'r', encoding='utf-8') as f:
                    src_content = f.read()
                if src_path.suffix == '.sol':
                    # Try enhanced translator first
                    if hasattr(VerifiedTranslator, 'translate_with_proof'):
                        base_content, _ = VerifiedTranslator().translate_with_proof(src_content)
                    else:
                        base_content = DeFiTranslator.translate_solidity(src_content)
                else:
                    base_content = DeFiTranslator.translate_rust(src_content)
            except Exception as e:
                return {"output": f"Translation error: {e}", "success": False}
            # Save base model (without custom specs)
            base_file = MODELS_DIR / f"{src_path.stem}_base.pml"
            with open(base_file, 'w', encoding='utf-8') as f:
                f.write(base_content)
        else:
            # Already a .pml model — read content
            try:
                with open(src_path, 'r', encoding='utf-8') as f:
                    base_content = f.read()
            except Exception as e:
                return {"output": f"Read error: {e}", "success": False}
            base_file = src_path

        # Step B: inject custom specs if provided
        verify_file = base_file
        if specs and specs.strip():
            # Strip any existing LTL blocks to avoid duplicates
            cleaned = re.sub(r'ltl\s+\w+\s*\{[^}]*\}', '', base_content, flags=re.DOTALL)
            combined = cleaned + "\n\n/* === CUSTOM SPECIFICATIONS === */\n" + specs
            verify_file = MODELS_DIR / f"{src_path.stem}_with_specs.pml"
            with open(verify_file, 'w', encoding='utf-8') as f:
                f.write(combined)

        # Step C: SPIN generation
        r = subprocess.run(["spin", "-a", str(verify_file)], capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR)
        if r.returncode != 0:
            return {"output": r.stdout + r.stderr, "success": False}

        # Step D: compile pan
        compile_r = subprocess.run(
            ["gcc", "-O3", "-o", str(LOGS_DIR / "pan"), "pan.c"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        if compile_r.returncode != 0:
            return {"output": compile_r.stdout + compile_r.stderr, "success": False}

        # Step E: run model checker
        run_r = subprocess.run(
            [str(LOGS_DIR / "pan"), "-a"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        combined = run_r.stdout + run_r.stderr

        # Step F: parse statistics
        states_match = re.search(r"(\d+) states, stored", combined)
        trans_match  = re.search(r"(\d+) transitions", combined)
        depth_match  = re.search(r"depth reached (\d+)", combined)
        states_stored = int(states_match.group(1)) if states_match else 0
        transitions  = int(trans_match.group(1)) if trans_match else 0
        depth        = int(depth_match.group(1)) if depth_match else 0

        # Step G: determine success (SPIN returns 0 even on property violations)
        has_violations = False
        if run_r.returncode != 0:
            has_violations = True
        else:
            err_match = re.search(r"errors:\s*([1-9]\d*)", combined)
            if err_match or "acceptance cycle" in combined.lower() or "assertion violated" in combined.lower():
                has_violations = True
        success = not has_violations

        # Step H: preserve trail file if failed
        trace_path = ""
        if not success:
            for trail_name in ["pan.trail", "translated_output.pml.trail"]:
                src_trail = PROJECT_DIR / trail_name
                if src_trail.exists():
                    dest_trail = LOGS_DIR / trail_name
                    root_trail = PROJECT_DIR / trail_name
                    try:
                        shutil.copy2(src_trail, dest_trail)
                        if src_trail != root_trail:
                            shutil.copy2(src_trail, root_trail)
                        trace_path = str(dest_trail)
                    except Exception:
                        pass
                    break

        # Step I: save log
        ts      = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = str(LOGS_DIR / f"spin_verification_{ts}.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(
                    f"=== SPIN VERIFICATION LOG ===\n"
                    f"timestamp: {datetime.now().isoformat()}\n"
                    f"file: {source_path}\n"
                    f"specs: {specs}\n\n"
                    f"--- STDOUT ---\n{combined}\n\n--- STDERR ---\n{run_r.stderr}"
                )
        except Exception:
            pass

        return {
            "output":       combined,
            "success":      success,
            "states_stored": states_stored,
            "transitions":  transitions,
            "depth":        depth,
            "log_path":     log_path,
            "trace_path":   trace_path,
            "ltl_results":  _parse_spin_ltl(combined),
        }

    else:
        # Non-SPIN tools: run directly
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "output": r.stdout + r.stderr,
            "success": r.returncode == 0,
        }
    cmd = cmd_map.get(tool, [])
    if not cmd:
        raise ValueError(f"No command for {tool}")

    if tool == "SPIN":
        # SPIN: ensure .pml model, translate if needed, inject custom specs
        src_path = Path(source_path)
        verify_file = ""
        if src_path.suffix in ('.sol', '.rs'):
            try:
                from translator import VerifiedTranslator, DeFiTranslator
                with open(src_path, 'r', encoding='utf-8') as f:
                    src_content = f.read()
                if src_path.suffix == '.sol':
                    translated_content, _ = VerifiedTranslator().translate_with_proof(src_content) \
                        if hasattr(VerifiedTranslator, 'translate_with_proof') else (DeFiTranslator.translate_solidity(src_content), [])
                else:  # .rs
                    translated_content = DeFiTranslator.translate_rust(src_content)
            except Exception as e:
                return {"output": f"Translation error: {e}", "success": False}
            pml_path = MODELS_DIR / f"{src_path.stem}_translated.pml"
            with open(pml_path, 'w', encoding='utf-8') as f:
                f.write(translated_content)
            verify_file = str(pml_path)
        else:
            verify_file = source_path
            with open(verify_file, 'r', encoding='utf-8') as f:
                translated_content = f.read()

        # Inject custom LTL specs if provided
        if specs.strip():
            # Remove existing auto-generated LTL blocks to avoid duplicates
            cleaned = re.sub(r'ltl\s+\w+\s*\{[^}]*\}', '', translated_content, flags=re.DOTALL)
            # Append user specs
            verify_content = cleaned + "\n\n/* === CUSTOM SPECIFICATIONS === */\n" + specs
            verify_file_tmp = MODELS_DIR / f"{src_path.stem}_with_specs.pml"
            with open(verify_file_tmp, 'w', encoding='utf-8') as f:
                f.write(verify_content)
            verify_file = str(verify_file_tmp)

        # Step 1: Generate pan.c
        r = subprocess.run(["spin", "-a", verify_file], capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR)
        if r.returncode != 0:
            return {"output": r.stdout + r.stderr, "success": False}

        # Step 2: Compile pan
        compile_r = subprocess.run(
            ["gcc", "-O3", "-o", str(LOGS_DIR / "pan"), "pan.c"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        if compile_r.returncode != 0:
            return {"output": compile_r.stdout + compile_r.stderr, "success": False}

        # Step 3: Run verification
        run_r = subprocess.run(
            [str(LOGS_DIR / "pan"), "-a"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        combined = run_r.stdout + run_r.stderr

        # Parse stats
        states_match = re.search(r"(\d+) states, stored", combined)
        trans_match  = re.search(r"(\d+) transitions", combined)
        depth_match  = re.search(r"depth reached (\d+)", combined)
        states_stored = int(states_match.group(1)) if states_match else 0
        transitions  = int(trans_match.group(1)) if trans_match else 0
        depth        = int(depth_match.group(1)) if depth_match else 0

        # Determine success (SPIN returns 0 even on property violations)
        has_violations = False
        if run_r.returncode != 0:
            has_violations = True
        else:
            err_match = re.search(r"errors:\s*([1-9]\d*)", combined)
            if err_match or "acceptance cycle" in combined.lower() or "assertion violated" in combined.lower():
                has_violations = True
        success = not has_violations

        # Preserve trail file if verification failed
        trace_path = ""
        if not success:
            for trail_name in ["pan.trail", "translated_output.pml.trail"]:
                src_trail = PROJECT_DIR / trail_name
                if src_trail.exists():
                    dest_trail = LOGS_DIR / trail_name
                    root_trail = PROJECT_DIR / trail_name
                    try:
                        shutil.copy2(src_trail, dest_trail)
                        if src_trail != root_trail:
                            shutil.copy2(src_trail, root_trail)
                        trace_path = str(dest_trail)
                    except Exception:
                        pass
                    break

        # Save log
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = str(LOGS_DIR / f"spin_verification_{ts}.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== SPIN VERIFICATION LOG ===\ntimestamp: {datetime.now().isoformat()}\nfile: {source_path}\nspecs: {specs}\n\n--- STDOUT ---\n{combined}\n\n--- STDERR ---\n{run_r.stderr}")
        except Exception:
            pass

        return {
            "output": combined,
            "success": success,
            "states_stored": states_stored,
            "transitions": transitions,
            "depth": depth,
            "log_path": log_path,
            "trace_path": trace_path,
            "ltl_results": _parse_spin_ltl(combined),
        }
    else:
        # For other tools, just run the command
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "output": r.stdout + r.stderr,
            "success": r.returncode == 0,
        }
    cmd = cmd_map.get(tool, [])
    if not cmd:
        raise ValueError(f"No command for {tool}")
    
    if tool == "SPIN":
        # For SPIN, ensure we have a .pml model. Translate if needed.
        src_path = Path(source_path)
        if src_path.suffix in ('.sol', '.rs'):
            # Translate to Promela
            try:
                # Try to use the enhanced translator if available
                try:
                    from translator import VerifiedTranslator
                    translator = VerifiedTranslator()
                    translated_content, _ = translator.translate_with_proof(src_content)
                except (ImportError, AttributeError):
                    # Fall back to basic DeFiTranslator
                    from translator import DeFiTranslator
                    if src_path.suffix == '.sol':
                        translated_content = DeFiTranslator.translate_solidity(src_content)
                    else:
                        translated_content = DeFiTranslator.translate_rust(src_content)
            except Exception as e:
                return {"output": f"Translation error: {e}", "success": False}
            
            # Save translated model
            pml_path = MODELS_DIR / f"{src_path.stem}_translated.pml"
            with open(pml_path, 'w', encoding='utf-8') as f:
                f.write(translated_content)
            verify_file = str(pml_path)
        else:
            verify_file = source_path
        
        # Step 1: Generate pan.c
        r = subprocess.run(["spin", "-a", verify_file], capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR)
        if r.returncode != 0:
            return {"output": r.stdout + r.stderr, "success": False}
        
        # Step 2: Compile pan
        compile_r = subprocess.run(
            ["gcc", "-O3", "-o", str(LOGS_DIR / "pan"), "pan.c"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        if compile_r.returncode != 0:
            return {"output": compile_r.stdout + compile_r.stderr, "success": False}
        
        # Step 3: Run verification
        run_r = subprocess.run(
            [str(LOGS_DIR / "pan"), "-a"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        combined = run_r.stdout + run_r.stderr
        
        # Parse stats
        states_match = re.search(r"(\d+) states, stored", combined)
        trans_match  = re.search(r"(\d+) transitions", combined)
        depth_match  = re.search(r"depth reached (\d+)", combined)
        states_stored = int(states_match.group(1)) if states_match else 0
        transitions  = int(trans_match.group(1)) if trans_match else 0
        depth        = int(depth_match.group(1)) if depth_match else 0
        
        # Determine success (SPIN returns 0 even on property violations)
        has_violations = False
        if run_r.returncode != 0:
            has_violations = True
        else:
            err_match = re.search(r"errors:\s*([1-9]\d*)", combined)
            if err_match or "acceptance cycle" in combined.lower() or "assertion violated" in combined.lower():
                has_violations = True
        success = not has_violations
        
        # Preserve trail file if verification failed
        trace_path = ""
        if not success:
            for trail_name in ["pan.trail", "translated_output.pml.trail"]:
                src_trail = PROJECT_DIR / trail_name
                if src_trail.exists():
                    dest_trail = LOGS_DIR / trail_name
                    root_trail = PROJECT_DIR / trail_name
                    try:
                        shutil.copy2(src_trail, dest_trail)
                        if src_trail != root_trail:
                            shutil.copy2(src_trail, root_trail)
                        trace_path = str(dest_trail)
                    except Exception:
                        pass
                    break
        
        # Save log
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = str(LOGS_DIR / f"spin_verification_{ts}.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== SPIN VERIFICATION LOG ===\ntimestamp: {datetime.now().isoformat()}\nfile: {source_path}\n\n--- STDOUT ---\n{combined}\n\n--- STDERR ---\n{run_r.stderr}")
        except Exception:
            pass
        
        return {
            "output": combined,
            "success": success,
            "states_stored": states_stored,
            "transitions": transitions,
            "depth": depth,
            "log_path": log_path,
            "trace_path": trace_path,
            "ltl_results": _parse_spin_ltl(combined),
        }
    else:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "output": r.stdout + r.stderr,
            "success": r.returncode == 0,
        }
    cmd = cmd_map.get(tool, [])
    if not cmd:
        raise ValueError(f"No command for {tool}")
    
    if tool == "SPIN":
        # Step 1: Generate pan.c
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR)
        if r.returncode != 0:
            return {"output": r.stdout + r.stderr, "success": False}
        
        # Step 2: Compile pan
        compile_r = subprocess.run(
            ["gcc", "-O3", "-o", str(LOGS_DIR / "pan"), "pan.c"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        if compile_r.returncode != 0:
            return {"output": compile_r.stdout + compile_r.stderr, "success": False}
        
        # Step 3: Run verification
        run_r = subprocess.run(
            [str(LOGS_DIR / "pan"), "-a"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_DIR
        )
        combined = run_r.stdout + run_r.stderr
        
        # Parse stats
        states_stored = int(re.search(r"(\d+) states, stored", combined).group(1)) if re.search(r"(\d+) states, stored", combined) else 0
        transitions = int(re.search(r"(\d+) transitions", combined).group(1)) if re.search(r"(\d+) transitions", combined) else 0
        depth = int(re.search(r"depth reached (\d+)", combined).group(1)) if re.search(r"depth reached (\d+)", combined) else 0
        
        # Preserve trail file if verification failed
        trace_path = ""
        success = (run_r.returncode == 0) and ("errors: 0" in combined or not re.search(r"errors:\s*[1-9]", combined))
        
        if not success:
            # Look for trail in common locations
            for trail_name in ["pan.trail", "translated_output.pml.trail"]:
                src_trail = PROJECT_DIR / trail_name
                if src_trail.exists():
                    dest_trail = LOGS_DIR / trail_name
                    shutil.copy2(src_trail, dest_trail)
                    trace_path = str(dest_trail)
                    # Also copy to root for compatibility
                    root_trail = PROJECT_DIR / trail_name
                    if src_trail != root_trail:
                        shutil.copy2(src_trail, root_trail)
                    break
        
        # Save log
        log_path = str(LOGS_DIR / f"spin_verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        try:
            with open(log_path, "w") as f:
                f.write(f"=== SPIN VERIFICATION LOG ===\ntimestamp: {datetime.now().isoformat()}\nfile: {source_path}\n\n--- STDOUT ---\n{combined}\n\n--- STDERR ---\n{run_r.stderr}")
        except Exception:
            pass
        
        return {
            "output": combined,
            "success": success,
            "states_stored": states_stored,
            "transitions": transitions,
            "depth": depth,
            "log_path": log_path,
            "trace_path": trace_path,
            "ltl_results": _parse_spin_ltl(combined),
        }
    else:
        # For other tools, just run the command
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "output": r.stdout + r.stderr,
            "success": r.returncode == 0,
        }
