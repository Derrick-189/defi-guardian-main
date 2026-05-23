#!/usr/bin/env bash
set -euo pipefail

# Installs system packages required to build Python DB bindings and other native deps
# Run with sudo: sudo ./scripts/install_system_deps.sh
# If the direct exec fails, run with bash:
#   sudo bash ./scripts/install_system_deps.sh

apt-get update
apt-get install -y build-essential libpq-dev python3-dev pkg-config 

echo "System packages installed. Activate your venv and run:"
echo "  source .venv/bin/activate && pip install -r requirements.txt"
