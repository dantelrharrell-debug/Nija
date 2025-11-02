# nija_client.py
import os
import logging
from decimal import Decimal
from coinbase_advanced_py.client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Environment variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_URL = "https://api.coinbase.com"

if not API_KEY or not API_SECRET:
    raise RuntimeError("[NIJA] ❌ Missing Coinbase API credentials")

# --- Initialize Coinbase client (JWT Auth mode not needed here) ---
try:
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
    logger.info("[NIJA] ✅ Live Coinbase client connected")
except Exception as e:
    logger.error(f"[NIJA] ❌ Coinbase client init failed: {e}")
    raise

# --- Balance helper ---
def get_usd_balance():
    """Fetch USD balance from Coinbase."""
    try:
        accounts = client.get_accounts()
        for acc in accounts.get("accounts", []):
            if acc["currency"] == "USD":
                balance = Decimal(acc["available_balance"]["value"])
                logger.info(f"[NIJA] 💵 USD Balance: {balance}")
                return balance
        logger.warning("[NIJA] USD account not found")
        return Decimal("0.0")
    except Exception as e:
        logger.error(f"[NIJA] ⚠️ Error fetching balance: {e}")
        return Decimal("0.0")
