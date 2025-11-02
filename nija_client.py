# -----------------------------
# nija_client.py (LIVE ONLY)
# -----------------------------
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# Import CoinbaseClient
# -----------------------------
try:
    from coinbase_advanced_py import CoinbaseClient
except ModuleNotFoundError:
    logger.error("[NIJA] coinbase_advanced_py not installed. Cannot start live bot.")
    raise SystemExit("[NIJA] Install 'coinbase_advanced_py' before running live.")

# -----------------------------
# Initialize client
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    logger.error("[NIJA] Missing Coinbase API credentials. Cannot run live.")
    raise SystemExit("[NIJA] Set COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE.")

try:
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_passphrase=API_PASSPHRASE
    )
    logger.info("[NIJA] CoinbaseClient initialized successfully!")
except Exception as e:
    logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
    raise SystemExit("[NIJA] Cannot start bot without valid Coinbase credentials.")

# -----------------------------
# Helper function
# -----------------------------
def get_usd_balance() -> float:
    try:
        accounts = client.get_accounts()
        usd_account = next((a for a in accounts if a["currency"] == "USD"), None)
        return float(usd_account["balance"]) if usd_account else 0.0
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        raise SystemExit("[NIJA] Cannot fetch balance. Check Coinbase credentials or network.")
