# nija_client.py
import os
import time
import logging
from decimal import Decimal

# ✅ Correct import for v1.8.2
from coinbase_advanced_py import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NijaBot")

# Load API keys from environment variables
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

# Initialize Coinbase client
client = CoinbaseClient(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
    passphrase=COINBASE_API_PASSPHRASE,
    sandbox=False  # ✅ Change to True if testing in sandbox
)

def start_trading():
    """
    Example trading loop.
    Replace this with your real trading logic.
    """
    logger.info("🔥 Nija bot started trading loop...")
    try:
        while True:
            # Fetch accounts as a simple test
            accounts = client.get_accounts()
            logger.info(f"Accounts: {accounts}")
            time.sleep(10)  # wait 10 seconds between checks
    except KeyboardInterrupt:
        logger.info("🛑 Nija bot stopped manually.")
    except Exception as e:
        logger.exception(f"💥 Error in trading loop: {e}")
