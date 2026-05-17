#!/bin/bash
# DeFi Guardian - Simple Launcher

cd ~/defi_guardian

# Check if already running
if pgrep -f "defi_guardian_shortcut.py" > /dev/null; then
    echo "DeFi Guardian is already running"
    exit 1
fi

# Launch the application
python3 defi_guardian_shortcut.py
