import os, re, json
from pathlib import Path

def _load_state_graph() -> dict | None:
    # Use project root for consistency
    graph_file = Path(__file__).parent.parent / "generated" / "reports" / "state_graph.json"
    if graph_file.exists():
        try:
            return json.loads(graph_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def _property_category(formula: str) -> str:
    if not formula:
        return ""
    if re.search(r"\b(liveness|reachability|response|progress|fairness|eventually)\b|<>|\bU\b|until", formula, re.IGNORECASE):
        return "LIVENESS"
    if re.search(r"\b(safety|invariant|always|assert)\b|\[\]", formula, re.IGNORECASE):
        return "SAFETY"
    return ""

def _parse_spin_output_to_steps(output: str, ltl_results: list[dict] | None = None) -> tuple[list, list[str]]:
    """Extract detailed trace steps from raw SPIN output for the viewer."""
    steps = []
    warnings: list[str] = []
    if not output:
        return steps, warnings

    formula_map = {}
    if ltl_results:
        formula_map = {r.get("name", ""): r.get("formula", "") for r in ltl_results}

    # Capture unreachable claim/proctype sections from SPIN output.
    unreached_pat = re.compile(
        r"unreached in (proctype|claim) ([\w_]+)\s*\n((?:\s+.*\n)+?)(?=\n\s*pan:|\n\n|$)",
        re.IGNORECASE,
    )
    for m in unreached_pat.finditer(output):
        category = m.group(1)
        name = m.group(2)
        lines = [ln for ln in m.group(3).splitlines() if ln.strip()]
        warnings.append(
            f"Unreached {category} '{name}' with {len(lines)} unreachable trace lines."
        )

    # Parse detailed trace steps from SPIN output
    trace_pattern = re.compile(
        r"^\s*(\d+):\s*proc\s+(\d+)\s*\((.*?):\d+\)\s*(.*?):(\d+)\s*\(state\s+(\d+)\)\s*\[(.*?)\]",
        re.MULTILINE
    )

    assignment_pattern = re.compile(r"(?<![=!<>])\b([A-Za-z_]\w*)\s*=\s*([^=][^,;\]]*)")

    current_vars = {}

    for match in trace_pattern.finditer(output):
        step_num = int(match.group(1))
        proc_id = int(match.group(2))
        proc_name = match.group(3).strip()
        file_path = match.group(4)
        line_num = int(match.group(5))
        state_id = int(match.group(6))
        action = match.group(7).strip()

        updates = {}
        step_vars_before = current_vars.copy()
        if action and '=' in action:
            for part in re.split(r'[;,]', action):
                part = part.strip()
                assign_match = assignment_pattern.match(part)
                if assign_match:
                    var_name = assign_match.group(1).strip()
                    var_value = assign_match.group(2).strip()
                    updates[var_name] = var_value
                    current_vars[var_name] = var_value

        is_error = bool(re.search(r"\b(assert|violation|error|claim)\b", action, re.IGNORECASE))
        if not is_error and proc_name == "-":
            is_error = True
        if not is_error and re.search(r"reachability|liveness|claim", proc_name, re.IGNORECASE):
            is_error = True

        step = {
            "step": step_num,
            "proc_id": proc_id,
            "proc_name": proc_name,
            "line": line_num,
            "file": file_path,
            "state": state_id,
            "variables_before": step_vars_before,
            "variables_after": current_vars.copy(),
            "updates": updates,
            "variables": current_vars.copy(),
            "raw": match.group(0).strip(),
            "action": action,
            "is_error": is_error,
        }
        steps.append(step)

    final_vars_pattern = re.compile(r"^\s*(\w+)\s*=\s*(.+)$", re.MULTILINE)
    final_vars_section = re.search(r"spin: trail ends after \d+ steps.*?(?=^\s*\d+:|\Z)", output, re.DOTALL | re.MULTILINE)
    if final_vars_section and steps:
        final_vars = {}
        for match in final_vars_pattern.finditer(final_vars_section.group(0)):
            var_name = match.group(1).strip()
            var_value = match.group(2).strip()
            final_vars[var_name] = var_value
        steps[-1]["variables_after"] = final_vars
        steps[-1]["variables"] = final_vars

    if steps and not any(s.get("is_error") for s in steps):
        if re.search(r"acceptance cycle|assertion violated|error|violation", output, re.IGNORECASE):
            steps[-1]["is_error"] = True

    sections = re.split(r"--- LTL (\w+) ---", output)
    for i in range(1, len(sections), 2):
        name = sections[i]
        body = sections[i + 1]
        errors = 0
        acceptance_cycle = False

        err_match = re.search(r"errors:\s*([0-9]+)", body)
        if err_match: errors = int(err_match.group(1))

        cycle_match = re.search(r"acceptance cycle \(at depth\s*([0-9]+)\)", body, re.IGNORECASE)
        if cycle_match: acceptance_cycle = True

        if errors > 0 or acceptance_cycle:
            for step in steps:
                if step.get("proc_name") == name or name in step.get("action", ""):
                    step["is_error"] = True
                    step["category"] = _property_category(formula_map.get(name, "") or name)
                    break

    return steps, warnings

def _spin_recs(passed: bool, trace_steps: list[dict] | None = None, output: str = "") -> list[str]:
    if passed:
        return [
            "All LTL properties verified — no counterexample found.",
            "Consider adding more invariants to strengthen the specification.",
            "Run mutation testing with Gambit to validate rule coverage.",
        ]

    recommendations = []
    failure_type = "unknown"
    depth = None
    if output:
        lower_output = output.lower()
        if "acceptance cycle" in lower_output:
            failure_type = "liveness"
            m = re.search(r"acceptance cycle \(at depth\s*([0-9]+)\)", output, re.IGNORECASE)
            if m: depth = int(m.group(1))
        elif "assertion violated" in lower_output or "assert(" in lower_output:
            failure_type = "safety"
        elif "error" in lower_output or "violation" in lower_output:
            failure_type = "safety"

    error_step = None
    if trace_steps:
        for step in trace_steps:
            if step.get("is_error"):
                error_step = step
                break
        if not error_step and trace_steps:
            error_step = trace_steps[-1]

    step_num = error_step.get("step") if error_step else None
    vars_after = error_step.get("variables_after", {}) if error_step else {}

    details = []
    for key in ("user_collateral", "user_debt", "health_factor", "liquidation_executed", "amount", "price_eth", "state"):
        if key in vars_after:
            details.append(f"{key}={vars_after[key]}")

    if failure_type == "liveness":
        recommendations.append(f"Step {step_num or '?'}: acceptance cycle detected (liveness violation).")
    elif failure_type == "safety":
        recommendations.append(f"Step {step_num or '?'}: safety violation detected.")
    else:
        recommendations.append(f"Step {step_num or '?'}: counterexample found.")

    if details:
        recommendations.append(f"Key values: {', '.join(details[:5])}.")

    recommendations.extend([
        "Review the LTL property and its encoder.",
        "Inspect variable values at each step.",
        "Consider adding require() guards or fairness constraints.",
    ])
    return recommendations
