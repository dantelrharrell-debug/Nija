# nija_client.py
import os
from coinbase_advanced_py import CoinbaseAdvanced

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = None  # Advanced Trade keys do not need this

        if not all([self.api_key, self.api_secret]):
            raise ValueError("Missing Coinbase API key or secret")

        # Initialize client
        self.client = CoinbaseAdvanced(
            api_key=self.api_key,
            api_secret=self.api_secret
        )
        print("CoinbaseClient initialized successfully ✅")

    def get_accounts(self):
        """Returns all accounts from Advanced Trade"""
        return self.client.get_accounts()


if __name__ == "__main__":
    # Quick test
    c = CoinbaseClient()
    try:
        accounts = c.get_accounts()
        if not accounts:
            print("No accounts returned. Check key permissions or IP allowlist ❌")
        else:
            print("Connected accounts:")
            for a in accounts:
                name = a.get("name", "<unknown>")
                bal = a.get("balance", {})
                print(f"{name}: {bal.get('amount','0')} {bal.get('currency','?')}")
    except Exception as e:
        print("Error connecting to Coinbase:", e)
