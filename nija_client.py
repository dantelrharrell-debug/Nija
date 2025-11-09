# nija_client_cdp.py

import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseAdvancedClient:
    def __init__(self, api_key=None, api_secret=None, org_id=None, base_url=None):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.org_id   = org_id   or os.getenv("COINBASE_ORG_ID")
        self.base     = base_url or os.getenv("COINBASE_API_BASE", "https://api.coinbase.com/api/v3/brokerage")

        logger.info("CoinbaseAdvancedClient initialized")
        logger.info(f"Base URL = {self.base}")

        if not (self.api_key and self.api_secret and self.org_id):
            logger.error("Missing API key, secret or org_id for Coinbase Advanced.")
            raise RuntimeError("Invalid Coinbase Advanced credentials.")

    def _bearer_token(self):
        """
        Builds a simple JWT token for Advanced Trade if needed.
        NOTE: Depending on your API key type, you may use JWT or HMAC.
        This example uses HMAC‑style on `/accounts` endpoint for simplicity.
        """
        timestamp = str(int(time.time()))
        method = "GET"
        path   = "/accounts"
        body   = ""

        message = timestamp + method + path + body
        hmac_key = self.api_secret.encode("utf‑8")
        signature = hmac.new(hmac_key, message.encode("utf‑8"), hashlib.sha256).digest()
        token     = base64.b64encode(signature).decode("utf‑8")

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": token,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-ORG": self.org_id,
            "Content-Type": "application/json"
        }

    def fetch_accounts(self):
        """
        Fetch list of accounts (balances etc) for Coinbase Advanced endpoint.
        Official endpoint: GET {base}/accounts (see docs)   [oai_citation:0‡Coinbase Developer Docs](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/accounts/list-accounts?utm_source=chatgpt.com)
        """
        url = f"{self.base}/accounts"
        headers = self._bearer_token()

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("accounts") or data.get("data") or []
            logger.info(f"Fetched {len(accounts)} account(s).")
            return accounts
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return []

    def get_balances(self):
        """
        Returns a dict of currency → available/active balance
        """
        accounts = self.fetch_accounts()
        balances = {}
        for acct in accounts:
            currency = acct.get("currency") or acct.get("asset") or acct.get("money_currency")
            # Try different shapes:
            amt = None
            if "available_balance" in acct and isinstance(acct["available_balance"], dict):
                amt = acct["available_balance"].get("value")
            elif "balance" in acct:
                amt = acct["balance"]
            elif "available" in acct:
                amt = acct["available"]
            try:
                balances[currency] = float(amt or 0)
            except Exception:
                balances[currency] = 0.0
        return balances

# === Test snippet ===
if __name__ == "__main__":
    client = CoinbaseAdvancedClient()
    accounts = client.fetch_accounts()
    print("Accounts (raw):", accounts)
    balances = client.get_balances()
    print("Balances:", balances)
    print("USD balance:", balances.get("USD", balances.get("USDC", 0)))
