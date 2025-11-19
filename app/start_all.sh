#!/usr/bin/env bash
set -euo pipefail

echo "== start_all.sh: Starting Nija Trading Bot container =="

# --- 1️⃣ Check required environment variables ---
REQUIRED_VARS=("GITHUB_PAT" "COINBASE_API_KEY" "COINBASE_API_SECRET" "COINBASE_ACCOUNT_ID")
for VAR in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!VAR:-}" ]; then
    echo "❌ ERROR: $VAR is not set. Please set it and redeploy."
    exit 1
  fi
done

# --- 2️⃣ Install Coinbase SDK at runtime ---
echo "⏳ Installing coinbase-advanced from GitHub..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
echo "✅ coinbase-advanced installed"

# --- 3️⃣ Start the trading bot in background ---
echo "⚡ Starting Nija trading bot..."
python3 - <<'PYTHON_EOF' &
import os
import logging
from time import sleep
from coinbase_advanced.client import Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Load environment variables
API_KEY = os.environ["COINBASE_API_KEY"]
API_SECRET = os.environ["COINBASE_API_SECRET"]
ACCOUNT_ID = os.environ["COINBASE_ACCOUNT_ID"]

# Initialize Coinbase client
try:
    client = Client(api_key=API_KEY, api_secret=API_SECRET)
    logging.info("✅ Coinbase client initialized")
except Exception as e:
    logging.error(f"❌ Failed to initialize Coinbase client: {e}")
    raise SystemExit(e)

# Verify funded account
try:
    accounts = client.get_accounts()
    funded = next((a for a in accounts if a["id"] == ACCOUNT_ID), None)
    if funded:
        logging.info(f"✅ Connected to funded account: {funded['currency']} | Balance: {funded['balance']['amount']}")
    else:
        logging.error("❌ Funded account not found. Check COINBASE_ACCOUNT_ID")
        raise SystemExit("Invalid funded account")
except Exception as e:
    logging.error(f"❌ Coinbase connection failed: {e}")
    raise SystemExit(e)

# --- Trading loop ---
logging.info("⚡ Trading loop starting...")
while True:
    try:
        accounts = client.get_accounts()
        for acct in accounts:
            logging.info(f"Account: {acct['currency']} | Balance: {acct['balance']['amount']}")
        # TODO: insert your live trading logic here
        sleep(10)
    except Exception as e:
        logging.error(f"❌ Error in trading loop: {e}")
        sleep(5)
PYTHON_EOF

# --- 4️⃣ Start Gunicorn web server for health checks ---
echo "🚀 Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
