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
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional
        self.base_url = "https://api.coinbase.com"
        self.use_jwt = False

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Missing Coinbase API_KEY or API_SECRET")

        # Detect JWT usage
        if not self.passphrase:
            self.use_jwt = True
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        else:
            log.info("✅ Passphrase provided. Using Base API key.")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _generate_jwt(self):
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,
            "sub": self.api_key
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    def _send_request(self, endpoint, method="GET"):
        if self.use_jwt:
            url = f"{self.base_url}{endpoint}"
            headers = {
                "Authorization": f"Bearer {self._generate_jwt()}",
                "Content-Type": "application/json"
            }
        else:
            url = f"{self.base_url}/v2{endpoint}"
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": self._generate_jwt(),
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json"
            }

        try:
            response = requests.request(method, url, headers=headers)
            if response.status_code == 401:
                raise RuntimeError(f"❌ 401 Unauthorized. Check key permissions and JWT usage.")
            if response.status_code >= 400:
                raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
            return response.json()
        except requests.RequestException as e:
            raise RuntimeError(f"❌ Request exception: {e}")

    def get_all_accounts(self):
        endpoint = "/accounts" if self.use_jwt else "/accounts"
        data = self._send_request(endpoint)
        return data.get("data", [])

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for acct in accounts:
            if acct.get("currency") == "USD":
                return float(acct.get("balance", {}).get("amount", 0))
        return 0.0


# Helpers to mimic old imports
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
