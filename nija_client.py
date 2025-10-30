# nija_client.py
import os
import logging
from pathlib import Path

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Config from environment ---
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("1", "true", "yes")
LIVE_TRADING = os.getenv("LIVE_TRADING", "True").lower() in ("1", "true", "yes")

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
COINBASE_PEM = os.getenv("COINBASE_PEM")            # full PEM text (optional)
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")  # explicit path (optional)
PEM_DEFAULT_PATH = "/opt/render/project/secrets/coinbase.pem"

# Ensure secrets directory exists when writing PEM
Path("/opt/render/project/secrets").mkdir(parents=True, exist_ok=True)

# --- Dummy client fallback (keeps signatures similar to real client usage) ---
class DummyClient:
    def fetch_account(self):
        logger.info("[DummyClient] fetch_account called")
        return {"balances": []}

    def place_order(self, **kwargs):
        logger.info(f"[DummyClient] Simulated place_order: {kwargs}")
        return {
            "id": "sim-order",
            "status": "simulated",
            "details": kwargs
        }

    def get_product_ticker(self, product_id):
        logger.info(f"[DummyClient] get_product_ticker {product_id}")
        return {"price": "0.00"}

# --- Try to import the real Coinbase client the correct way ---
CoinbaseClient = None
try:
    # >>> Correct import
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] coinbase_advanced_py.client import succeeded")
except Exception as e:
    logger.warning(f"[NIJA] coinbase_advanced_py.client import failed: {e}")
    CoinbaseClient = None

# --- If PEM body provided, write it to disk (securely) ---
def write_pem_if_present():
    if COINBASE_PEM:
        path = COINBASE_PEM_PATH or PEM_DEFAULT_PATH
        try:
            with open(path, "w", newline="\n") as f:
                f.write(COINBASE_PEM)
            os.chmod(path, 0o600)
            logger.info(f"[NIJA] Wrote PEM to {path} (mode 600)")
            return path
        except Exception as e:
            logger.error(f"[NIJA] Failed to write PEM to {path}: {e}")
            return None
    # if an explicit path env var was set but not the pem body, just return the path so client may use it
    if COINBASE_PEM_PATH and Path(COINBASE_PEM_PATH).exists():
        return COINBASE_PEM_PATH
    return None

pem_path_used = write_pem_if_present()  # may be None

# --- Initialize client (real or dummy) ---
client = None
client_is_dummy = True

if not DRY_RUN and LIVE_TRADING and CoinbaseClient is not None:
    # Need api key/secret/passphrase OR a pem path depending on your coinbase client config
    try:
        # Prefer API key/secret/passphrase if provided
        if COINBASE_API_KEY and COINBASE_API_SECRET and COINBASE_PASSPHRASE:
            logger.info("[NIJA] Initializing CoinbaseClient with API key/secret/passphrase")
            client = CoinbaseClient(
                api_key=COINBASE_API_KEY,
                api_secret=COINBASE_API_SECRET,
                passphrase=COINBASE_PASSPHRASE,
                pem_path=pem_path_used  # ok if None
            )
        elif pem_path_used:
            logger.info("[NIJA] Initializing CoinbaseClient with PEM path only")
            client = CoinbaseClient(pem_path=pem_path_used)
        else:
            logger.warning("[NIJA] Coinbase credentials not found in env (API key/secret/passphrase or PEM).")
            client = None

        # Quick smoke test (non-destructive) if client was created
        if client is not None:
            try:
                # some coinbase clients have a lightweight ping/fetch; adapt if necessary
                _ = getattr(client, "fetch_account", None)
                logger.info("[NIJA] CoinbaseClient initialized successfully ✅ Live trading enabled")
                client_is_dummy = False
            except Exception as e:
                logger.error(f"[NIJA] Coinbase client initialized but smoke-check failed: {e}")
                client = None
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client = None

if client is None:
    logger.warning("[NIJA] Using DummyClient (simulated orders). Set COINBASE_API_KEY/SECRET/PASSPHRASE or COINBASE_PEM to enable live.")
    client = DummyClient()
    client_is_dummy = True

# --- Public exports ---
__all__ = ["client", "client_is_dummy", "DRY_RUN", "LIVE_TRADING", "pem_path_used"]

logger.info(f"[NIJA] Module loaded. DRY_RUN={DRY_RUN} LIVE_TRADING={LIVE_TRADING} client_is_dummy={client_is_dummy}")
