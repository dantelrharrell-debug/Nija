# nija_client.py
import os, time, json, requests, jwt
from loguru import logger

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, passphrase=None, base=None, advanced_mode=True):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.base = base or os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.advanced_mode = advanced_mode
        logger.info(f"CoinbaseClient initialized — Advanced mode: {self.advanced_mode}")

    def _get_headers(self):
        timestamp = str(int(time.time()))
        # You need to create a valid CB-ACCESS-SIGN if you want live trading
        signature = "FAKE_SIGNATURE"  # Replace with HMAC calculation for live trades
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def fetch_accounts(self):
        try:
            if self.advanced_mode:
                url = f"{self.base}/v2/accounts"  # Correct CDP endpoint
            else:
                url = f"{self.base}/accounts"    # Pro API endpoint

            resp = requests.get(url, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error fetching accounts: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching accounts: {e}")
            return []

    # Optional backward-compatible aliases
    def get_accounts(self):
        return self.fetch_accounts()

    def get_balances(self):
        accounts = self.fetch_accounts()
        # Example: extract USD balance
        usd_balance = 0
        if accounts and "data" in accounts:
            for a in accounts["data"]:
                if a.get("currency") == "USD":
                    usd_balance = float(a.get("balance", 0))
        return usd_balance

# Example test
if __name__ == "__main__":
    client = CoinbaseClient(advanced_mode=True)
    print(client.fetch_accounts())
    print("USD balance:", client.get_balances())
