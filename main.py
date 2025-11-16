import os
import sys
from loguru import logger

# -----------------------------
# Optional: Adjust Python path
# -----------------------------
# If nija_client.py is inside /app/app, add that to sys.path
possible_paths = ["/app", "/app/app"]
for path in possible_paths:
    if os.path.exists(path):
        sys.path.insert(0, path)

# -----------------------------
# Import Nija client
# -----------------------------
try:
    from nija_client import CoinbaseClient, load_private_key
except ModuleNotFoundError as e:
    logger.error(f"Cannot find nija_client.py. Check your file location. Error: {e}")
    sys.exit(1)

# -----------------------------
# Load PEM Key
# -----------------------------
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "/opt/railway/secrets/coinbase.pem")
try:
    private_key = load_private_key(COINBASE_PEM_PATH)
except Exception as e:
    logger.error(f"Failed to load PEM private key: {e}")
    sys.exit(1)

# -----------------------------
# Setup Coinbase Client
# -----------------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

try:
    client = CoinbaseClient(
        api_key=COINBASE_API_KEY,
        organization_id=COINBASE_ORG_ID,
        private_key=private_key
    )
    logger.info("Coinbase client initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    sys.exit(1)

# -----------------------------
# Test connection
# -----------------------------
try:
    accounts = client.get_accounts()
    logger.info(f"Successfully fetched accounts: {accounts}")
except Exception as e:
    logger.error(f"Error fetching accounts: {e}")

# -----------------------------
# Main Bot Loop
# -----------------------------
import time

logger.info("Nija Bot starting main loop...")
while True:
    # Example heartbeat
    logger.info("Heartbeat...")
    time.sleep(10)
