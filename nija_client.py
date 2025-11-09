# === Backwards-compatibility aliases ===
def _alias_if_missing():
    try:
        if not hasattr(CoinbaseClient, "get_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.get_accounts = CoinbaseClient.fetch_accounts

        if not hasattr(CoinbaseClient, "get_balances"):
            if hasattr(CoinbaseClient, "get_account_balances"):
                CoinbaseClient.get_balances = CoinbaseClient.get_account_balances
            elif hasattr(CoinbaseClient, "get_accounts"):
                def _get_balances(self):
                    return self.get_accounts()
                CoinbaseClient.get_balances = _get_balances

        if not hasattr(CoinbaseClient, "list_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.list_accounts = CoinbaseClient.fetch_accounts

    except Exception:
        pass

_alias_if_missing()

# nija_client.py

import os, json, requests, jwt, time
from loguru import logger

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, passphrase=None, base=None):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.base = base or os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        logger.info("CoinbaseClient initialized")

    def fetch_accounts(self):
        # minimal example endpoint call
        url = f"{self.base}/v2/accounts"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": "FAKE_SIGNATURE",
            "CB-ACCESS-TIMESTAMP": str(int(time.time())),
            "CB-ACCESS-PASSPHRASE": self.passphrase,
        }
        try:
            resp = requests.get(url, headers=headers)
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return []
