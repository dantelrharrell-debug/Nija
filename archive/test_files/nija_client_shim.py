# repo-root/nija_client_shim.py
# Shim to keep compatibility with older imports (scripts that expect `from app.nija_client import CoinbaseClient`)

from nija_client import CoinbaseClient  # re-export
__all__ = ["CoinbaseClient"]
