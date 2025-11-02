# nija_client.py
import os
import logging
from decimal import Decimal
from coinbase_advanced_py.client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# --- Load Coinbase credentials
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET_PATH = os.getenv("COINBASE_PEM_PATH", "/opt/render/project/secrets/coinbase.pem")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", None)  # optional

if not API_KEY or not API_SECRET_PATH:
    raise RuntimeError("❌ Missing Coinbase API_KEY or API_SECRET_PATH in environment")

# -----------------------------
# --- Ensure PEM file exists
# -----------------------------
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
if PEM_CONTENT:
    from pathlib import Path
    pem_path = Path(API_SECRET_PATH)
    pem_path.parent.mkdir(parents=True, exist_ok=True)
    pem_path.write_text(PEM_CONTENT)
    logger.info(f"[NIJA] PEM written to {pem_path}")

# -----------------------------
# --- Initialize live client
# -----------------------------
try:
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret_path=API_SECRET_PATH,
        api_passphrase=API_PASSPHRASE,
    )
    logger.info("[NIJA] Coinbase RESTClient initialized ✅")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase RESTClient: {e}")
    raise

# -----------------------------
# --- Optional: expose class
# -----------------------------
CLIENT_CLASS = CoinbaseClient

# -----------------------------
# --- Helper: Get USD balance
# -----------------------------
def get_usd_balance(client_obj=None) -> Decimal:
    """
    Fetch USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails.
    """
    client_obj = client_obj or client
    try:
        accounts = client_obj.get_accounts()
        usd_account = next(acc for acc in accounts if acc['currency'] == 'USD')
        balance = Decimal(usd_account['balance']['amount'])
        return balance
    except StopIteration:
        logger.warning("[NIJA] No USD account found")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        return Decimal(0)

# -----------------------------
# --- Test initialization
# -----------------------------
if __name__ == "__main__":
    balance = get_usd_balance()
    logger.info(f"[NIJA-TEST] USD Balance: {balance}")
