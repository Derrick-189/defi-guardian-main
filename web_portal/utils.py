import os, re, json, subprocess, tempfile
from pathlib import Path
from datetime import datetime

def create_custom_state_diagram(pml_content: str, model_name: str = "Model", 
                                 show_procs: bool = True, show_vars: bool = True, 
                                 show_invariants: bool = True, theme: str = "dark",
                                 filter_str: str = "", behavioral: bool = False,
                                 active_step: int = -1, trace_steps: list = None) -> str:
    """
    Generate a Graphviz DOT diagram from PML content.
    Includes subgraphs for processes, state variables, and invariants.
    Enhanced with Behavioral CFG parsing and Trace Projection.
    """
    # Theme-based colors
    is_dark = theme == "dark"
    bg_color = "transparent"
    font_color = "#ffffff" if is_dark else "#1a1a2e"
    node_bg = "#1a1a2e" if is_dark else "#f0f4f8"
    accent = "#00ffcc"
    accent2 = "#ffa500"
    accent3 = "#ff4444"
    border_color = "#00ffcc"
    trace_color = "#ffff00" # Neon yellow for trace

    # Create DOT content
    dot_content = 'digraph G {\n'
    dot_content += '    rankdir=TB;\n'
    dot_content += f'    node [shape=box, style="filled,rounded", fillcolor="{node_bg}", fontcolor="{font_color}", color="{border_color}", fontname="Arial", fontsize=12];\n'
    dot_content += f'    edge [color="{accent}", penwidth=2, fontcolor="{accent}", fontsize=10];\n'
    dot_content += f'    bgcolor="{bg_color}";\n\n'

    # Extract common elements
    active_proctypes = re.findall(r'active\s+proctype\s+(\w+)', pml_content)
    is_sol = ".sol" in model_name.lower() or "contract" in pml_content[:500].lower()

    # Helper to check filter
    def matches_filter(s: str) -> bool:
        if not filter_str: return False
        return filter_str.lower() in s.lower()

    # Determine active node from trace
    active_proc_name = ""
    active_line = -1
    if trace_steps and active_step >= 0 and active_step < len(trace_steps):
        step = trace_steps[active_step]
        active_proc_name = step.get("proc_name", "")
        active_line = step.get("line", -1)

    # ── Behavioral CFG Parsing ──────────────────────────────────────────────
    if behavioral:
        if is_sol:
            # Solidity Behavioral: Extract contracts and functions
            contracts = re.findall(r'contract\s+(\w+)\s*\{(.*?)\}', pml_content, re.DOTALL)
            if not contracts:
                # Try interface or library
                contracts = re.findall(r'(?:interface|library)\s+(\w+)\s*\{(.*?)\}', pml_content, re.DOTALL)
                
            for i, (name, body) in enumerate(contracts):
                dot_content += f'    subgraph cluster_sol_{name} {{\n'
                dot_content += f'        label="Contract: {name}";\n'
                dot_content += f'        fontcolor="{accent}";\n'
                dot_content += f'        style="rounded,dashed";\n'
                dot_content += f'        color="{accent}";\n'
                
                # Extract functions as behavioral nodes
                funcs = re.findall(r'function\s+(\w+)\s*\(.*?\)', body)
                prev_node = None
                for j, func in enumerate(funcs[:15]):
                    node_id = f"S{i}_F{j}"
                    is_active = (func.lower() in active_proc_name.lower())
                    highlight = f', penwidth=4, color="{trace_color}"' if is_active else ""
                    dot_content += f'        {node_id} [label="{func}()", shape="rect", fillcolor="{node_bg}"{highlight}];\n'
                    if prev_node:
                        dot_content += f'        {prev_node} -> {node_id} [style="invis"];\n'
                    prev_node = node_id
                dot_content += '    }\n\n'
        else:
            # PML Behavioral: Extract all proctypes and their bodies
            proctype_blocks = re.findall(r'proctype\s+(\w+)\s*\((.*?)\)\s*\{(.*?)\}', pml_content, re.DOTALL)
            for i, (name, params, body) in enumerate(proctype_blocks):
                dot_content += f'    subgraph cluster_proc_{name} {{\n'
                dot_content += f'        label="Behavior: {name}";\n'
                dot_content += f'        fontcolor="{accent}";\n'
                dot_content += f'        style="rounded,dashed";\n'
                dot_content += f'        color="{accent}";\n'
                
                # Simple line-by-line parsing for behavioral steps
                lines = [ln.strip() for ln in body.split('\n') if ln.strip() and not ln.strip().startswith('//')]
                prev_node = None
                for j, line in enumerate(lines[:20]):
                    node_id = f"P{i}_L{j}"
                    label = line.replace('"', '\\"').strip()
                    if len(label) > 30: label = label[:27] + "..."
                    
                    is_active = (name == active_proc_name and (j + 1) == active_line)
                    highlight = f', penwidth=4, color="{trace_color}"' if is_active else ""
                    
                    dot_content += f'        {node_id} [label="{label}", shape="rect", fillcolor="{node_bg}"{highlight}];\n'
                    if prev_node:
                        dot_content += f'        {prev_node} -> {node_id};\n'
                    prev_node = node_id
                dot_content += '    }\n\n'
    else:
        # ── Standard Structural View ──────────────────────────────────────────
        if is_sol:
            # Solidity Structural: Contracts and Mappings/State Vars
            contracts = re.findall(r'contract\s+(\w+)', pml_content)
            if active_proctypes or contracts:
                dot_content += '    subgraph cluster_entities {\n'
                dot_content += '        label="System Entities";\n'
                dot_content += f'        fontcolor="{accent}";\n'
                dot_content += '        style="rounded,dashed";\n'
                dot_content += f'        color="{accent}";\n'
                entities = list(dict.fromkeys(active_proctypes + contracts))
                for i, entity in enumerate(entities[:10]):
                    is_active = (entity == active_proc_name)
                    highlight = f', penwidth=4, color="{trace_color}"' if is_active else (', penwidth=4, color="#ffffff"' if matches_filter(entity) else "")
                    dot_content += f'        E{i} [label="{entity}", shape="ellipse", fillcolor="{node_bg}", fontcolor="{accent}"{highlight}];\n'
                dot_content += '    }\n\n'
        else:
            if active_proctypes and show_procs:
                dot_content += '    subgraph cluster_processes {\n'
                dot_content += '        label="Active Processes";\n'
                dot_content += f'        fontcolor="{accent}";\n'
                dot_content += '        style="rounded,dashed";\n'
                dot_content += f'        color="{accent}";\n'
                for i, proc in enumerate(active_proctypes):
                    is_active = (proc == active_proc_name)
                    highlight = f', penwidth=4, color="{trace_color}"' if is_active else (', penwidth=4, color="#ffffff"' if matches_filter(proc) else "")
                    dot_content += f'        P{i} [label="{proc}", shape="ellipse", fillcolor="{node_bg}", fontcolor="{accent}"{highlight}];\n'
                dot_content += '    }\n\n'
    
    # Add state variables subgraph (Enhanced for Solidity)
    if is_sol:
        state_vars = re.findall(r'(?:uint|int|bool|address|string|mapping)\s+(?:public|private|internal)?\s*(\w+)\s*[;=]', pml_content)
    else:
        state_vars = re.findall(r'(?:int|byte|bool|short)\s+(\w+)\s*=', pml_content)
        
    if state_vars and show_vars:
        dot_content += '    subgraph cluster_variables {\n'
        dot_content += '        label="State Variables";\n'
        dot_content += f'        fontcolor="{accent2}";\n'
        dot_content += '        style="rounded,dashed";\n'
        dot_content += f'        color="{accent2}";\n'
        for i, var in enumerate(list(dict.fromkeys(state_vars))[:10]):
            highlight = ', penwidth=4, color="#ffffff"' if matches_filter(var) else ""
            dot_content += f'        V{i} [label="{var}", shape="note", fillcolor="{node_bg}", fontcolor="{accent2}"{highlight}];\n'
        dot_content += '    }\n\n'
    
    # Add invariants subgraph (Enhanced for Solidity)
    if is_sol:
        assertions = re.findall(r'require\s*\((.*?)\)', pml_content)
    else:
        assertions = re.findall(r'assert\s*\((.*?)\)', pml_content)
    if assertions and show_invariants:
        dot_content += '    subgraph cluster_invariants {\n'
        dot_content += '        label="Security Invariants";\n'
        dot_content += f'        fontcolor="{accent3}";\n'
        dot_content += '        style="rounded,dashed";\n'
        dot_content += f'        color="{accent3}";\n'
        for i, assertion in enumerate(list(dict.fromkeys(assertions))[:5]):
            label = assertion.replace('"', '\\"').strip()
            if len(label) > 40: label = label[:37] + "..."
            highlight = ', penwidth=4, color="#ffffff"' if matches_filter(assertion) else ""
            dot_content += f'        A{i} [label="{label}", shape="diamond", fillcolor="{node_bg}", fontcolor="{accent3}"{highlight}];\n'
        dot_content += '    }\n\n'
    
    # Standard flow nodes
    dot_content += f'    init [label="Initial State", shape="circle", fillcolor="{accent}", fontcolor="black"];\n'
    dot_content += '    verify [label="Model Checking", shape="box"];\n'
    dot_content += '    check [label="Invariant Validation", shape="diamond"];\n'
    dot_content += '    result [label="Verification Result", shape="box"];\n'
    
    dot_content += '    init -> verify;\n'
    dot_content += '    verify -> check;\n'
    
    if show_invariants:
        for i in range(min(len(assertions), 5)):
            dot_content += f'    check -> A{i} [label="Check", style="dotted"];\n'
            dot_content += f'    A{i} -> result [style="dotted"];\n'
    
    if not assertions or not show_invariants:
        dot_content += '    check -> result [label="Success"];\n'

    dot_content += '}\n'
    return dot_content

def generate_state_diagram_output(dot_content: str, format: str = "svg") -> bytes | None:
    """Convert DOT content to requested format using the 'dot' command."""
    try:
        # Use bytes for PDF/PNG, string for SVG
        output_format = f"-T{format}"
        process = subprocess.Popen(
            ['dot', output_format],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(input=dot_content.encode('utf-8'))
        if process.returncode == 0:
            return stdout
        else:
            print(f"Graphviz error: {stderr.decode('utf-8')}")
            return None
    except Exception as e:
        print(f"Failed to generate {format}: {e}")
        return None

def generate_state_diagram_svg(dot_content: str) -> str | None:
    """Legacy helper for SVG string."""
    out = generate_state_diagram_output(dot_content, "svg")
    return out.decode('utf-8') if out else None

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
