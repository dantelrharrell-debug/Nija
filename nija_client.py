import os
import time
import jwt
import requests
import logging

# Setup logger
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # May be None
        self.base_url = "https://api.coinbase.com"

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Missing Coinbase API credentials")

        # Detect if we're using Advanced JWT (passphrase not required)
        self.use_jwt = self.passphrase is None
        if self.use_jwt:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        else:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _get_headers(self, method="GET", path="/"):
        if self.use_jwt:
            # Create JWT for Advanced API
            timestamp = int(time.time())
            payload = {
                "iat": timestamp,
                "exp": timestamp + 300,  # 5 minutes expiry
                "sub": self.api_key
            }
            token = jwt.encode(payload, self.api_secret, algorithm="HS256")

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        else:
            # Standard API headers
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": self.api_secret,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }
        return headers

    def _send_request(self, endpoint, method="GET", data=None):
        url = self.base_url + endpoint
        headers = self._get_headers(method, endpoint)
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data)
            else:
                raise ValueError("Unsupported HTTP method")

            if response.status_code not in [200, 201]:
                log.error(f"❌ Request failed: {response.status_code} {response.text}")
                if response.status_code == 401:
                    raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
                raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")

            return response.json()
        except requests.RequestException as e:
            log.error(f"❌ Request exception: {e}")
            raise RuntimeError(f"❌ Request exception: {e}")

    def get_all_accounts(self):
        endpoint = "/v2/accounts"
        data = self._send_request(endpoint)
        return data.get("data", [])

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for account in accounts:
            if account.get("currency") == "USD":
                return float(account.get("balance", {}).get("amount", 0))
        return 0.0


# Module-level helpers for nija_debug.py compatibility
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
