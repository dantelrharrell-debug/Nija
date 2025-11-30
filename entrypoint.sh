#!/bin/bash
set -e  # Exit immediately on any error

echo "=== STARTING NIJA TRADING BOT ==="

# Check if coinbase_advanced is installed
python3 - <<PYTHON
import importlib
import subprocess
import sys

package_name = "coinbase_advanced"

try:
    importlib.import_module(package_name)
    print(f"{package_name} module loaded successfully.")
except ModuleNotFoundError:
    print(f"{package_name} module NOT installed. Installing now...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "git+https://github.com/coinbase/coinbase-advanced-py.git"])
    print(f"{package_name} module installed successfully.")
PYTHON

# Start Gunicorn
exec gunicorn --config ./gunicorn.conf.py wsgi:app
