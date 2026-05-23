#!/usr/bin/env python3
"""
Counterexample Analyzer for DeFi Guardian
Parses SPIN trail files and generates readable reports
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

class CounterexampleAnalyzer:
    def __init__(self, project_dir=None):
        self.project_dir = project_dir or os.path.dirname(os.path.abspath(__file__))
        self.trail_file = os.path.join(self.project_dir, "translated_output.pml.trail")

    # ------------------------------------------------------------------
    # FIX: Call this before every new verification run so that a trail
    # left over from a previous run is never mistaken for a current one.
    # SPIN only writes a new trail when it finds an error; if the model
    # passes cleanly the old file stays on disk, causing the "file is
    # newer than trail" warning and a false counterexample report.
    # ------------------------------------------------------------------
    def clear_stale_trail(self):
        """Delete the trail file if it exists so the next run starts clean."""
        if os.path.exists(self.trail_file):
            try:
                os.unlink(self.trail_file)
            except OSError as e:
                print(f"Warning: could not remove stale trail file: {e}")

    def has_counterexample(self):
        """Check if a counterexample trail exists"""
        return os.path.exists(self.trail_file) and os.path.getsize(self.trail_file) > 0
    
    def analyze_with_spin(self, pml_file=None):
        """Use SPIN to analyze the counterexample trail"""
        if pml_file is None:
            pml_file = os.path.join(self.project_dir, "translated_output.pml")
        
        if not os.path.exists(pml_file):
            return "No Promela model found for counterexample analysis"
        
        if not self.has_counterexample():
            return "No counterexample trail found"

        # FIX: Warn explicitly if the trail pre-dates the model so the
        # caller can see the trail is stale rather than silently replaying
        # an old execution.
        pml_mtime = os.path.getmtime(pml_file)
        trail_mtime = os.path.getmtime(self.trail_file)
        if pml_mtime > trail_mtime:
            return (
                "⚠️  Stale trail detected: the Promela model is newer than the "
                "trail file. The trail was produced by a previous model and does "
                "not apply to the current one. Run clear_stale_trail() before "
                "re-verifying to avoid this."
            )
        
        try:
            result = subprocess.run(
                ["spin", "-t", "-p", pml_file],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.project_dir
            )
            return result.stdout if result.stdout else result.stderr
        except Exception as e:
            return f"Error analyzing counterexample: {e}"
    
    def get_structured_trace(self, pml_file=None):
        """Get a structured execution trace for UI display"""
        spin_output = self.analyze_with_spin(pml_file)
        if "No counterexample" in spin_output or "No Promela model" in spin_output or "Stale trail" in spin_output:
            return {"error": spin_output}

        steps = []
        current_vars = {}

        # SPIN 6.x replay output has two common formats:
        #
        # Format A (with -p -v flags):
        #   2:  proc  0 (Contract:1) translated_output.pml:44 (state 10)  [assert(!(paused))]
        #
        # Format B (older / -t only):
        #   1:  proc  0 (main) line   4 "test.pml" (state 1)  [x = 1]
        #
        # We try both patterns.

        pattern_a = re.compile(
            r'^\s*(\d+):\s*proc\s+(\d+)\s*\(([^)]+)\)\s+'
            r'(?:\S+):(\d+)\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?'
        )
        pattern_b = re.compile(
            r'^\s*(\d+):\s*proc\s+(\d+)\s*\(([^)]+)\)\s+'
            r'line\s+(\d+)\s+"([^"]+)"\s+\(state\s+(\d+)\)\s*(?:\[(.*)\])?'
        )
        # Variable assignment lines: "    varname = value"
        var_pattern = re.compile(r'^\s+(\w+)\s*=\s*(.+)$')

        current_step = None

        for line in spin_output.split('\n'):
            # Try format A
            m = pattern_a.match(line)
            if m:
                step_num, proc_id, proc_name, line_num, state_id, action = m.groups()
                prev_vars = current_vars.copy()
                updates = {}
                if action:
                    for part in action.split(','):
                        if '=' in part:
                            k, v = part.split('=', 1)
                            k, v = k.strip(), v.strip()
                            updates[k] = v
                            current_vars[k] = v
                current_step = {
                    "step":            int(step_num),
                    "proc_id":         int(proc_id),
                    "proc_name":       proc_name.strip(),
                    "line":            int(line_num),
                    "file":            pml_file or "model",
                    "state":           int(state_id),
                    "variables_before": prev_vars.copy(),
                    "variables_after":  current_vars.copy(),
                    "updates":         updates,
                    "variables":       current_vars.copy(),
                    "raw":             line.strip(),
                    "action":          action.strip() if action else "",
                }
                steps.append(current_step)
                continue

            # Try format B
            m = pattern_b.match(line)
            if m:
                step_num, proc_id, proc_name, line_num, filename, state_id, action = m.groups()
                prev_vars = current_vars.copy()
                updates = {}
                if action:
                    for part in action.split(','):
                        if '=' in part:
                            k, v = part.split('=', 1)
                            k, v = k.strip(), v.strip()
                            updates[k] = v
                            current_vars[k] = v
                current_step = {
                    "step":            int(step_num),
                    "proc_id":         int(proc_id),
                    "proc_name":       proc_name.strip(),
                    "line":            int(line_num),
                    "file":            filename,
                    "state":           int(state_id),
                    "variables_before": prev_vars.copy(),
                    "variables_after":  current_vars.copy(),
                    "updates":         updates,
                    "variables":       current_vars.copy(),
                    "raw":             line.strip(),
                    "action":          action.strip() if action else "",
                }
                steps.append(current_step)
                continue

            # Variable assignment line following a step
            if current_step:
                m = var_pattern.match(line)
                if m:
                    k, v = m.group(1).strip(), m.group(2).strip()
                    current_step["variables_before"] = current_step.get("variables", {}).copy()
                    current_step["variables"][k] = v
                    current_step["updates"][k] = v
                    current_vars[k] = v
                    current_step["variables_after"] = current_vars.copy()
                    continue

            # LTL violation message
            if "ltl" in line.lower() and ("violated" in line.lower() or "acceptance" in line.lower()):
                steps.append({"type": "violation", "message": line.strip()})
            elif "assertion violated" in line.lower() or "error:" in line.lower():
                steps.append({"type": "violation", "message": line.strip()})

        return {
            "steps":           steps,
            "final_variables": current_vars,
            "pml_file":        pml_file,
            "raw_output":      spin_output,
        }
    
    def generate_report(self, pml_file=None):
        """Generate a comprehensive counterexample report"""
        report = []
        report.append("="*70)
        report.append("COUNTEREXAMPLE ANALYSIS REPORT")
        report.append("="*70)
        report.append("")
        
        if not self.has_counterexample():
            report.append("✅ No counterexample found - All properties verified!")
            return "\n".join(report)
        
        report.append("❌ COUNTEREXAMPLE FOUND!")
        report.append("")
        
        spin_output = self.analyze_with_spin(pml_file)
        if spin_output:
            report.append("📋 SPIN GUIDED SIMULATION:")
            report.append("-"*50)
            report.append(spin_output)
            report.append("")
        
        structured_trace = self.get_structured_trace(pml_file)
        if "steps" in structured_trace:
            report.append("📊 EXECUTION TRACE:")
            report.append("-"*50)
            for step in structured_trace["steps"][:50]:
                report.append(f"  Step {step['step']}: {step['raw']}")
            report.append("")
        
        report.append("🔧 RECOMMENDATIONS:")
        report.append("-"*50)
        report.append("1. Review the LTL properties for correctness")
        report.append("2. Check if the model accurately represents the system")
        report.append("3. Verify that invariants are properly defined")
        report.append("4. Consider adding more constraints to the model")
        
        return "\n".join(report)
    
    def save_report(self, filename=None):
        """Save the counterexample report to a dedicated folder with timestamp"""
        report = self.generate_report()
        
        # Create dedicated reports folder
        reports_dir = os.path.join(self.project_dir, "reports", "counterexamples")
        os.makedirs(reports_dir, exist_ok=True)
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"counterexample_{timestamp}.log"
            
        report_path = os.path.join(reports_dir, filename)
        with open(report_path, 'w') as f:
            f.write(report)
        return report_path


def analyze_counterexample_from_file(pml_path, trail_path=None):
    """Convenience function to analyze counterexample from given files"""
    analyzer = CounterexampleAnalyzer(os.path.dirname(pml_path))
    return analyzer.generate_report(pml_path)