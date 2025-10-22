# ----- nija_client.py -----
import os
import logging

# optional: simple logging
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("nija.client")

CLIENT = None  # fallback reference for other modules
client = None  # lowercase alias

# Try to import coinbase_advanced_py
try:
    from coinbase_advanced_py.client import CoinbaseClient as CoinbaseAdvancedClient
except Exception:
    CoinbaseAdvancedClient = None
    _logger.warning("coinbase_advanced_py not installed or failed to import.")

def attach_coinbase_client_from_env():
    """
    Attempt to instantiate a Coinbase client from environment variables.
    - Uses COINBASE_KEY, COINBASE_SECRET, optionally COINBASE_PASSPHRASE
    - Returns a client object or None (simulation mode)
    """
    api_key = os.getenv("COINBASE_KEY") or os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_SECRET") or os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_PASSPHRASE")  # optional

    # --- DEBUG LOG for missing keys ---
    if not api_key or not api_secret:
        _logger.info(f"Coinbase keys not found. KEY={api_key}, SECRET={api_secret}")
        _logger.info("Running in simulation mode (no live trades).")
        return None

    # --- Try to instantiate coinbase_advanced_py ---
    if CoinbaseAdvancedClient is not None:
        try:
            _logger.info("Instantiating coinbase_advanced_py CoinbaseClient from env vars.")
            c = CoinbaseAdvancedClient(api_key=api_key, api_secret=api_secret)
            _logger.info("Coinbase client instantiated successfully.")
            return c
        except Exception as e:
            _logger.exception("Failed to instantiate CoinbaseAdvancedClient: %s", e)

    # If no client could be instantiated, fallback to simulation
    _logger.warning("No compatible Coinbase client library available or instantiation failed. Running in simulation mode.")
    return None

# Attach client at import
client = attach_coinbase_client_from_env()
CLIENT = client
# ----- end nija_client.py -----
