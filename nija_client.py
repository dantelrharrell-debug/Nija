import os
import time
import hmac
import hashlib
import json
import logging
import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if self.api_key and self.api_secret:
            if self.passphrase:
                log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")
            else:
                log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        else:
            raise RuntimeError("❌ Coinbase API credentials missing")

    def _send_request(self, endpoint, method="GET", data=None, use_jwt=None):
        url = self.base_url + endpoint
        headers = {}

        # Determine which auth to use
        if use_jwt is None:
            use_jwt = not self.passphrase

        if use_jwt:
            headers["Authorization"] = f"Bearer {self.api_secret}"
        else:
            timestamp = str(int(time.time()))
            body = json.dumps(data) if data else ""
            message = timestamp + method.upper() + endpoint + body
            signature = hmac.new(
                self.api_secret.encode(), message.encode(), hashlib.sha256
            ).hexdigest()
            headers.update({
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
            })

        response = requests.request(method, url, headers=headers, json=data)
        if response.status_code in (200, 201):
            return response.json()
        else:
            log.error(f"❌ Request failed ({'JWT' if use_jwt else 'Classic'}): "
                      f"{response.status_code} {response.text}")
            raise RuntimeError(f"❌ Request failed: {response.status_code}")

    def get_all_accounts(self):
        endpoint = "/v2/accounts"
        try:
            return self._send_request(endpoint, use_jwt=not self.passphrase)["data"]
        except RuntimeError as e:
            # Fallback if JWT fails and Classic is available
            if not self.passphrase:
                log.warning("⚠️ JWT failed. Trying Classic API key if available...")
                if self.passphrase:
                    return self._send_request(endpoint, use_jwt=False)["data"]
            raise e

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for a in accounts:
            if a.get("currency") == "USD":
                return float(a.get("balance", {}).get("amount", 0))
        return 0.0


# Helper functions for debug script
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
