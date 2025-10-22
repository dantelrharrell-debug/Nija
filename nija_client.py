cat > nija_client.py <<'PY'
# nija_client.py - minimal, non-circular client attachment
import sys, os
# ensure vendor/ is visible if you keep coinbase client in vendor
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

import logging
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("nija.client")

CLIENT = None
client = None

# Try import of coinbase library (defensive)
try:
    from coinbase_advanced_py.client import CoinbaseClient as CoinbaseAdvancedClient
except Exception:
    CoinbaseAdvancedClient = None
    _logger.warning("coinbase_advanced_py not installed or failed to import.")

def attach_coinbase_client_from_env():
    api_key = os.getenv("COINBASE_KEY") or os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_SECRET") or os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_PASSPHRASE")
    if not api_key or not api_secret:
        _logger.info(f"Coinbase keys not found. KEY={api_key}, SECRET={api_secret}")
        _logger.info("Running in simulation mode (no live trades).")
        return None

    if CoinbaseAdvancedClient is not None:
        try:
            _logger.info("Instantiating CoinbaseAdvancedClient.")
            c = CoinbaseAdvancedClient(api_key=api_key, api_secret=api_secret)
            _logger.info("Coinbase client instantiated.")
            return c
        except Exception as e:
            _logger.exception("Failed to instantiate CoinbaseAdvancedClient: %s", e)

    _logger.warning("No compatible Coinbase client library available. Running in simulation mode.")
    return None

# Attach client (safe, no imports from other project modules)
client = attach_coinbase_client_from_env()
CLIENT = client
PY
