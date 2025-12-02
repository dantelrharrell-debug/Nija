#!/bin/bash
# ===============================
# start.sh - Launch NIJA Trading Bot
# ===============================

# Exit immediately if a command exits with a non-zero status
set -e

# Optional: print each command before executing (for debug)
# set -x

# Environment check
echo "Starting NIJA Trading Bot..."
echo "LIVE_TRADING=${LIVE_TRADING:-0}"

# Activate Python environment (if needed)
# In this Dockerfile, we use system Python, so this is not required

# Navigate to bot directory
cd ./bot || { echo "Bot directory not found!"; exit 1; }

# Run the main bot script
# Replace 'main.py' with your bot's entrypoint file if different
echo "Launching bot..."
python main.py

# Keep container alive if bot exits (optional)
# tail -f /dev/null
