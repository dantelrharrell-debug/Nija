# minimal initializer — safe import
try:
    from .client import CoinbaseClient
except Exception:
    pass
