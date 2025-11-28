# nija_client.py
import logging
import os
import time

LOG = logging.getLogger("nija.client")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Keep a simple flag so app.py can report if coinbase client is available
_coinbase_available = False

def coinbase_available():
    return _coinbase_available

def test_coinbase_connection():
    """
    Lightweight check that attempts to import the coinbase client and
    makes a tiny call-free validation. This is intentionally non-blocking
    and will not raise an exception that kills the process.
    """
    global _coinbase_available
    try:
        # Try import (this will be available if you installed coinbase_advanced package)
        from coinbase_advanced.client import Client  # may raise ModuleNotFoundError
        # Basic validation using env vars (do not attempt live network calls here)
        api_key = os.environ.get("COINBASE_API_KEY")
        api_secret = os.environ.get("COINBASE_API_SECRET")
        if not api_key or not api_secret:
            LOG.warning("COINBASE_API_KEY/SECRET not set — Coinbase client available but creds missing.")
            _coinbase_available = True
            return False
        # If we get here treat as available (don't perform live handshake here)
        LOG.info("coinbase_advanced available and credentials present.")
        _coinbase_available = True
        return True
    except ModuleNotFoundError:
        LOG.error("coinbase_advanced module not installed. Trading disabled.")
        _coinbase_available = False
        return False
    except Exception:
        LOG.exception("Unexpected error checking coinbase availability.")
        _coinbase_available = False
        return False
