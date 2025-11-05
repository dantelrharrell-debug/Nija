# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import logging
import jwt  # PyJWT library

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")


class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Coinbase API_KEY or API_SECRET missing")

        # Determine mode
        if self.passphrase:
            self.mode = "STANDARD"
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")
        else:
            self.mode = "JWT"
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _get_headers(self, method: str, path: str, body: str = "") -> dict:
        """
        Generate headers for Coinbase API request
        Supports Standard key + passphrase or Advanced JWT
        """
        if self.mode == "STANDARD":
            timestamp = str(int(time.time()))
            message = timestamp + method.upper() + path + body
            hmac_key = base64.b64decode(self.api_secret)
            signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
            signature_b64 = base64.b64encode(signature).decode()
            return {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature_b64,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }
        elif self.mode == "JWT":
            token = jwt.encode(
                {"iat": int(time.time())},
                self.api_secret,
                algorithm="HS256"
            )
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        else:
            raise RuntimeError("❌ Invalid client mode")

    def _send_request(self, path: str, method: str = "GET", body: str = "") -> dict:
        url = self.base_url + path
        headers = self._get_headers(method, path, body)
        response = requests.request(method, url, headers=headers, data=body)
        if response.status_code == 401:
            raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
        if response.status_code >= 400:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    def get_all_accounts(self) -> list:
        endpoint = "/v2/accounts"
        return self._send_request(endpoint)["data"]

    def get_usd_spot_balance(self) -> float:
        accounts = self.get_all_accounts()
        for acct in accounts:
            if acct.get("currency") == "USD":
                return float(acct.get("balance", {}).get("amount", 0.0))
        return 0.0


# Module-level client
client = CoinbaseClient()

# Helper functions for debug.py
def get_all_accounts():
    return client.get_all_accounts()


def get_usd_spot_balance():
    return client.get_usd_spot_balance()
