#!/bin/bash
set -e

echo "=== Nija Deployment Script ==="

# 1️⃣ Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    echo "[INFO] Activating virtual environment..."
    source .venv/bin/activate
else
    echo "[ERROR] Virtual environment not found. Creating one..."
    python3 -m venv .venv
    source .venv/bin/activate
fi

# 2️⃣ Upgrade pip
echo "[INFO] Upgrading pip..."
pip install --upgrade pip

# 3️⃣ Remove any shadowing local folders
echo "[INFO] Removing shadowing folders..."
rm -rf ./coinbase_advanced_py
rm -rf ./coinbase-advanced-py

# 4️⃣ Install the official Coinbase client
echo "[INFO] Installing coinbase-advanced-py..."
pip install --upgrade coinbase-advanced-py

# 5️⃣ Confirm installation
echo "[INFO] Verifying installation..."
python3 - << EOF
try:
    from coinbase_advanced_py.client import CoinbaseClient
    print("[SUCCESS] CoinbaseClient is available")
except ModuleNotFoundError:
    print("[ERROR] CoinbaseClient not found")
EOF

# 6️⃣ Restart Nija service (Render automatically restarts on deploy)
echo "[INFO] Deployment complete. Commit changes and push to Render."
