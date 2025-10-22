# ----- Coinbase client attachment (safe, env-driven) -----
import os
import logging

# optional: configure simple logging if you don't already
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("nija.client")

CLIENT = None  # use uppercase here to avoid accidental overshadowing of "client" in other modules

# Try to import the common Coinbase client package(s). Be defensive — don't crash if not installed.
try:
    from coinbase_advanced_py.client import CoinbaseClient as CoinbaseAdvancedClient
except Exception:
    CoinbaseAdvancedClient = None

# You may also have another Coinbase library; attempt to import a second common one if you use it.
# try:
#     from coinbase_pro.client import CoinbaseProClient
# except Exception:
#     CoinbaseProClient = None

def attach_coinbase_client_from_env():
    """
    Attempt to instantiate a Coinbase client from environment variables.
    - Uses COINBASE_KEY and COINBASE_SECRET (and optionally COINBASE_PASSPHRASE)
    - Returns a client object or None.
    """
    api_key = os.getenv("COINBASE_KEY") or os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_SECRET") or os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_PASSPHRASE")  # optional for some clients

    if not api_key or not api_secret:
        _logger.info("Coinbase keys not found in env. Running in simulation mode (client None).")
        return None

    # Prefer the 'coinbase_advanced_py' library if available
    if CoinbaseAdvancedClient is not None:
        try:
            _logger.info("Instantiating coinbase_advanced_py CoinbaseClient from env vars.")
            client = CoinbaseAdvancedClient(api_key=api_key, api_secret=api_secret)
            _logger.info("Coinbase client instantiated (coinbase_advanced_py).")
            return client
        except Exception as e:
            _logger.exception("Failed to instantiate coinbase_advanced_py client: %s", e)

    # If other client libs are in use, add more instantiation attempts here...
    _logger.warning("No compatible Coinbase client library available or instantiation failed. Running in simulation mode.")
    return None

# Attach client at import time (safe)
client = attach_coinbase_client_from_env()
# Also expose client under CLIENT for other modules if needed
CLIENT = client
# ----- End client attachment -----
