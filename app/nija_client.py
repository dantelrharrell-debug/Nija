# /app/nija_client.py
# Minimal guaranteed-import stub for debugging import errors.
# If this file imports cleanly, start_bot.py will be able to import CoinbaseClient.

from typing import Any

class CoinbaseClient:
    """Minimal stub used to verify imports. Replace with full client after import test."""
    def __init__(self, *args, **kwargs):
        # store args for later debugging
        self._init_args = args
        self._init_kwargs = kwargs

    def fetch_accounts(self) -> list:
        # return a safe empty list so callers don't crash
        return []

    def get_balances(self) -> dict:
        return {}

# Backwards-compatible alias expected by start_bot.py
NijaCoinbaseClient = CoinbaseClient

# Small startup log to appear in container logs (helps diagnosing)
try:
    print("NIJA-IMPORT-OK: /app/nija_client.py loaded — CoinbaseClient and NijaCoinbaseClient defined")
except Exception:
    pass
