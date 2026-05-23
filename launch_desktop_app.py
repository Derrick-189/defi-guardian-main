#!/usr/bin/env python3
"""
Launch helper for DeFi Guardian desktop app.

This wrapper loads `.prusti.env` from the repository root if present,
then starts `desktop_app.py` as if it were executed directly.
"""

from __future__ import annotations

import os
import pathlib
import runpy
import sys

ROOT = pathlib.Path(__file__).resolve().parent


def load_env_file(env_path: pathlib.Path) -> None:
    if not env_path.exists():
        return

    with env_path.open() as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name:
                os.environ[name] = value


def main() -> None:
    os.chdir(ROOT)

    env_file = ROOT / ".prusti.env"
    if env_file.exists():
        print(f"Loading environment from {env_file}")
        load_env_file(env_file)
    else:
        print("No .prusti.env found; launching desktop app without extra environment")

    sys.argv = [str(ROOT / "desktop_app.py")] + sys.argv[1:]
    runpy.run_path(str(ROOT / "desktop_app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
