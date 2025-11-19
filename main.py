import os
import logging
import subprocess
import sys

# --- Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

# --- Load environment variables ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
COINBASE_ACCOUNT_ID = os.environ.get("COINBASE_ACCOUNT_ID")  # Your funded account
GITHUB_PAT = os.environ.get("GITHUB_PAT")

# --- Validate environment variables ---
required_vars = {
    "COINBASE_API_KEY": COINBASE_API_KEY,
    "COINBASE_API_SECRET": COINBASE_API_SECRET,
    "COINBASE_API_PASSPHRASE": COINBASE_API_PASSPHRASE,
    "COINBASE_ACCOUNT_ID": COINBASE_ACCOUNT_ID,
    "GITHUB_PAT": GITHUB_PAT
}

missing_vars = [name for name, val in required_vars.items() if not val]
if missing_vars:
    logging.error(f"❌ Missing environment variables: {missing_vars}")
    sys.exit("Set all required environment variables and redeploy.")

# --- Install coinbase-advanced at runtime ---
try:
    logging.info("⚡ Installing coinbase-advanced...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        f"git+https://{GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
    ])
    logging.info("✅ coinbase-advanced installed successfully")
except subprocess.CalledProcessError as e:
    logging.error(f"❌ Failed to install coinbase-advanced: {e}")
    sys.exit(e)

# --- Import after installation ---
from coinbase_advanced.client import Client

# --- Initialize Coinbase Advanced Client ---
try:
    client = Client(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET,
        api_passphrase=COINBASE_API_PASSPHRASE
    )
    logging.info("✅ Coinbase client initialized")
except Exception as e:
    logging.error(f"❌ Failed to initialize Coinbase client: {e}")
    sys.exit(e)

# --- Connect to funded account ---
try:
    accounts = client.get_accounts()
    funded_account = next((a for a in accounts if a["id"] == COINBASE_ACCOUNT_ID), None)
    if funded_account:
        logging.info(f"✅ Connected to funded account: {funded_account['currency']} | Balance: {funded_account['balance']['amount']}")
    else:
        logging.error("❌ Funded account ID not found")
        sys.exit("Check COINBASE_ACCOUNT_ID")
except Exception as e:
    logging.error(f"❌ Coinbase connection test failed: {e}")
    sys.exit(e)

# --- Bot ready ---
logging.info("⚡ Bot is ready and trading!")

# Example trading function
def trade_signal_example():
    logging.info("📈 Trading logic would execute here")
