# nija_client.py (root shim)
"""
Root shim so other modules can `from nija_client import CoinbaseClient`.
Implementation lives in app/nija_client.py
"""
try:
    from app.nija_client import CoinbaseClient  # type: ignore
except Exception as e:
    # Provide a helpful error when app/nija_client.py missing or fails to load.
    raise ImportError(f"Cannot find implementation at app/nija_client.py or it failed to import: {e}")

__all__ = ["CoinbaseClient"]
