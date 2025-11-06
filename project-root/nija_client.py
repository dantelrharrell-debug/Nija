# nija_client.py
import os

class CoinbaseClient:
    def __init__(self):
        # These can later be used for real API calls
        self.api_key = os.getenv("COINBASE_API_KEY", "demo_key")
        self.api_secret = os.getenv("COINBASE_API_SECRET", "demo_secret")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", "demo_pass")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

    def get_accounts(self):
        # Minimal dummy response for health check
        return [
            {"currency": "USD", "balance": "100.00"},
            {"currency": "BTC", "balance": "0.01"}
        ]
