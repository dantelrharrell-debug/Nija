# -----------------------------
# nija_client.py
# Fully live Coinbase client for Nija bot
# -----------------------------
import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# Load API credentials
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    raise SystemExit("[NIJA] ❌ Missing Coinbase API credentials! Cannot start live bot.")

# -----------------------------
# Import CoinbaseClient
# -----------------------------
try:
    from coinbase_advanced_py.client import CoinbaseClient
except ModuleNotFoundError:
    raise SystemExit("[NIJA] ❌ coinbase_advanced_py is not installed or missing client.py")
except Exception as e:
    raise SystemExit(f"[NIJA] ❌ Unexpected import error: {e}")

# -----------------------------
# Initialize live client
# -----------------------------
try:
    client = CoinbaseClient(API_KEY, API_SECRET)
    logger.info("[NIJA] ✅ Authenticated with CoinbaseClient successfully.")
except Exception as e:
    raise SystemExit(f"[NIJA] ❌ Failed to authenticate CoinbaseClient: {e}")

# -----------------------------
# Helper: fetch USD balance
# -----------------------------
def get_usd_balance(client):
    try:
        if hasattr(client, "get_usd_balance"):
            return client.get_usd_balance()
        elif hasattr(client, "get_account_balance"):
            return client.get_account_balance()
        else:
            raise AttributeError("Client missing balance method")
    except Exception as e:
        logger.exception(f"[NIJA] Error fetching USD balance: {e}")
        return Decimal("0")
