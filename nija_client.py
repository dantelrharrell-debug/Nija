# nija_client.py
import os
import logging

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# -----------------------------
# --- Environment keys -------
# -----------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional for REST client

# Simple check
if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    raise RuntimeError("[NIJA] Missing Coinbase API_KEY or API_SECRET — cannot start live trading")

logger.info(f"[NIJA-DEBUG] COINBASE_API_KEY present: {bool(COINBASE_API_KEY)}")
logger.info(f"[NIJA-DEBUG] COINBASE_API_SECRET present: {bool(COINBASE_API_SECRET)}")
logger.info(f"[NIJA-DEBUG] COINBASE_API_PASSPHRASE present: {bool(COINBASE_API_PASSPHRASE)}")

# -----------------------------
# --- Live REST client setup --
# -----------------------------
try:
    # Import your REST client here
    from coinbase_rest_client import RESTClient  # <- your upgraded REST client
    client = RESTClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, passphrase=COINBASE_API_PASSPHRASE)
    USE_DUMMY = False
    logger.info("[NIJA] Live RESTClient instantiated (no passphrase required)")
except Exception as e:
    logger.error(f"[NIJA] Failed to instantiate live client: {e}")
    raise RuntimeError("[NIJA] Cannot start live trading without a working RESTClient")
