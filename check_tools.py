#!/usr/bin/env python3
"""
Simple Tool Checker for DeFi Guardian
Checks all installed verification tools
"""

import subprocess
import sys
import os
import tempfile
import shutil

# Define tools to check
TOOLS = {
    # Core verification tools
    "SPIN": "spin -V",
    "Coq": "coqc --version",
    "Lean": "lean --version",
    "GCC": "gcc --version",
    
    # Rust verification tools
    "Prusti": "prusti-rustc --version",
    "Kani": "cargo kani --version",
    "Creusot": "creusot --version",
    
    # SMT solvers
    "Z3": "z3 --version",
    "CVC5": "cvc5 --version",
    
    # Build tools
    "Cargo": "cargo --version",
    "Rustc": "rustc --version",
    
    # Graphviz
    "Graphviz": "dot -V",
    
    # Elan (Lean version manager)
    "Elan": "elan --version",
}

def check_tool(name, command):
    """Check if a tool is installed"""
    try:
        cmd_parts = command.split()
        # Lean needs a longer timeout — elan may need a moment on first call
        timeout = 30 if name == "Lean" else 5
        result = subprocess.run(cmd_parts,
                               capture_output=True,
                               text=True,
                               timeout=timeout)
        if result.returncode == 0:
            output = result.stdout.split('\n')[0].strip()
            return True, output[:80]
        return False, result.stderr[:80] if result.stderr else "Unknown error"
    except FileNotFoundError:
        return False, "Not found"
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)[:80]


def build_prusti_env(base_env=None):
    """Build a clean env for Prusti by removing inherited PRUSTI_* flags."""
    env = dict(base_env or os.environ)
    for key in list(env.keys()):
        if key.startswith("PRUSTI_"):
            env.pop(key, None)
    try:
        prusti_bin_result = subprocess.run(
            ["which", "prusti-rustc"], capture_output=True, text=True, timeout=3
        )
        prusti_bin = prusti_bin_result.stdout.strip()
        if prusti_bin:
            prusti_home = os.path.dirname(os.path.realpath(prusti_bin))
            env["VIPER_HOME"] = os.path.join(prusti_home, "viper_tools")
    except Exception:
        pass
    return env


def prusti_health_check():
    """Run a tiny Prusti compile to detect config/toolchain breakages."""
    ok, msg = check_tool("Prusti", TOOLS["Prusti"])
    if not ok:
        return False, f"Prusti unavailable: {msg}"

    JAVA11 = "/usr/lib/jvm/java-1.11.0-openjdk-amd64"
    project_dir = tempfile.mkdtemp()
    try:
        src = os.path.join(project_dir, "lib.rs")
        with open(src, "w") as f:
            f.write("fn f(x: u64) -> u64 { x }\n")

        env = build_prusti_env()
        # Force Java 11 — Prusti v0.2.x Silver JARs are incompatible with Java 17+
        if os.path.isdir(JAVA11):
            env["JAVA_HOME"] = JAVA11
            lib_server = os.path.join(JAVA11, "lib", "server")
            lib_base   = os.path.join(JAVA11, "lib")
            existing   = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{lib_server}:{lib_base}" + (f":{existing}" if existing else "")

        # Point to bundled Z3 if available
        prusti_home = os.path.expanduser("~/.prusti")
        bundled_z3  = os.path.join(prusti_home, "viper_tools", "z3", "bin", "z3")
        if os.path.isfile(bundled_z3):
            env["Z3_EXE"] = bundled_z3

        result = subprocess.run(
            ["prusti-rustc", "--edition=2021", "--crate-type=lib", src],
            capture_output=True,
            text=True,
            timeout=90,   # Native binary needs ~30s on first run; Docker needs ~60s
            cwd=project_dir,
            env=env,
        )
        stderr = result.stderr or ""
        stdout = result.stdout or ""
        combined = stdout + stderr
        if "unknown configuration flag `home`" in combined:
            return False, "PRUSTI_* environment contamination (remove PRUSTI_HOME)"
        if "compiler unexpectedly panicked" in combined:
            # Distinguish JVM issue from other crashes
            if "NoClassDefFoundError" in combined or "NoopReporter" in combined:
                return False, "Prusti JVM error: Silver JAR incompatible with system Java (needs Java 11)"
            return False, "Prusti internal crash (toolchain incompatibility/bug)"
        if result.returncode != 0:
            last = (stderr.splitlines()[-1] if stderr.splitlines() else "Prusti failed")
            return False, last
        return True, "Prusti smoke test passed"
    except subprocess.TimeoutExpired:
        return False, "Prusti smoke test timed out (binary may still be functional)"
    except Exception as e:
        return False, f"Prusti smoke test error: {e}"
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)

def main():
    print("=" * 60)
    print("🔧 DEFI GUARDIAN - TOOL CHECKER")
    print("=" * 60)
    print()
    
    installed = 0
    total = len(TOOLS)
    
    # Check each tool
    for name, command in TOOLS.items():
        success, output = check_tool(name, command)
        if success:
            print(f"✅ {name:12} - {output}")
            installed += 1
        else:
            print(f"❌ {name:12} - {output}")
    
    print()
    print("=" * 60)
    print(f"📊 SUMMARY: {installed}/{total} tools installed")
    print("=" * 60)

    print()
    ok, details = prusti_health_check()
    print(f"{'✅' if ok else '❌'} Prusti Health - {details}")
    
    # Show installation commands for missing tools
    missing = [name for name in TOOLS.keys() if not check_tool(name, TOOLS[name])[0]]
    if missing:
        print()
        print("🔧 To install missing tools:")
        print("-" * 40)
        for name in missing:
            if name == "Prusti":
                print(f"  {name}: cargo install prusti && prusti-rustc --setup")
            elif name == "Kani":
                print(f"  {name}: cargo install --locked kani-verifier && cargo kani setup")
            elif name == "Creusot":
                print(f"  {name}: cargo install creusot")
            elif name == "Coq":
                print(f"  {name}: sudo apt install coq")
            elif name == "Lean":
                print(f"  {name}: curl https://elan.lean-lang.org/elan-init.sh -sSf | sh")
            elif name == "Elan":
                print(f"  {name}: curl https://elan.lean-lang.org/elan-init.sh -sSf | sh")
            elif name == "Z3":
                print(f"  {name}: sudo apt install z3")
            elif name == "CVC5":
                print(f"  {name}: Download from https://github.com/cvc5/cvc5/releases")
            elif name == "Graphviz":
                print(f"  {name}: sudo apt install graphviz")
            else:
                print(f"  {name}: sudo apt install {name.lower()}")

if __name__ == "__main__":
    main()


def check_all_tools():
    """Return a dict of tool_name -> {installed, status} for the web portal API."""
    results = {}
    for name, command in TOOLS.items():
        ok, msg = check_tool(name, command)
        results[name] = {
            'installed': ok,
            'version': msg if ok else '',
            'status': 'available' if ok else 'not_found',
            'detail': msg,
        }
    # Prusti gets a deeper health check
    if results.get('Prusti', {}).get('installed'):
        ok, detail = prusti_health_check()
        results['Prusti']['status'] = 'available' if ok else 'degraded'
        results['Prusti']['detail'] = detail
    return results
