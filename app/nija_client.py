import os
import time
import jwt
import requests
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")


class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase API key or secret")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT, no passphrase required).")

    def _get_headers(self):
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,  # token valid for 5 minutes
            "sub": self.api_key,
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": token,
            "Content-Type": "application/json",
        }
        return headers

    def _send_request(self, endpoint, method="GET", data=None):
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        log.debug(f"Requesting {method} {url} with headers {headers}")

        resp = requests.request(method, url, headers=headers, json=data)
        if resp.status_code != 200:
            log.error(f"❌ Request failed ({resp.status_code}): {resp.text}")
            raise RuntimeError(f"❌ {resp.status_code} {resp.text}")
        return resp.json()

    def get_all_accounts(self):
        """Return all Coinbase accounts (wallets)."""
        return self._send_request("/v2/accounts")

    def get_usd_spot_balance(self):
        """Return USD spot balance only."""
        accounts = self.get_all_accounts()
        usd_accounts = [
            acct for acct in accounts.get("data", []) if acct.get("currency") == "USD"
        ]
        if not usd_accounts:
            log.warning("⚠️ No USD account found")
            return 0.0
        return float(usd_accounts[0].get("balance", {}).get("amount", 0.0))


# Quick test if run directly
if __name__ == "__main__":
    client = CoinbaseClient()
    try:
        accounts = client.get_all_accounts()
        log.info(f"Accounts fetched: {accounts}")
        usd_balance = client.get_usd_spot_balance()
        log.info(f"USD Spot Balance: {usd_balance}")
    except RuntimeError as e:
        log.error(f"Failed to fetch data: {e}")
