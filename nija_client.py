# nija_client.py  (PROJECT ROOT — not /app)
# Minimal guaranteed-import stub. If this imports, start_bot.py will stop raising ImportError.

class CoinbaseClient:
    def __init__(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs

    def fetch_accounts(self):
        return []

    def get_balances(self):
        return {}

# Backwards-compatible alias
NijaCoinbaseClient = CoinbaseClient

# Quick log for deploy output (helps confirm the file used)
try:
    print("NIJA-IMPORT-OK: root nija_client.py loaded")
except Exception:
    pass
