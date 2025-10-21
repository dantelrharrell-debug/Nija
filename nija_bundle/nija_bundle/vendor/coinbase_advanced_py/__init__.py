# minimal initializer — expose CoinbaseClient if client.py defines it
try:
    from .client import CoinbaseClient
except Exception:
    # keep import-safe even if client.py missing or broken
    pass
