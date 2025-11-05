# nija_client.py
import os
import time
import jwt
import requests
import logging

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self):
        # Load keys
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # Standard API passphrase, can be None
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        
        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase API credentials")

        # Detect mode
        if self.passphrase:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")
            self.use_jwt = False
        else:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
            self.use_jwt = True
        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _get_jwt_headers(self):
        """Generate headers for Advanced JWT auth"""
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,  # 5 min validity
            "sub": self.api_key
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        return headers

    def _get_standard_headers(self):
        """Generate headers for standard API key auth"""
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-PASSPHRASE": self.passphrase or "",
            "CB-ACCESS-SIGN": self.api_secret,  # Using API secret directly for simplicity
            "Content-Type": "application/json"
        }

    def _send_request(self, endpoint, method="GET", data=None, use_jwt=False):
        url = self.base_url + endpoint
        headers = self._get_jwt_headers() if use_jwt else self._get_standard_headers()
        try:
            response = requests.request(method, url, headers=headers, json=data)
            if response.status_code not in [200, 201]:
                log.error(f"❌ Request failed: {response.status_code} {response.text}")
                raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
            return response.json()
        except Exception as e:
            log.error(f"❌ Request exception: {e}")
            raise

    # === Public helpers ===
    def get_all_accounts(self):
        """
        Fetch all accounts.
        Always uses standard API key + passphrase for compatibility.
        """
        endpoint = "/v2/accounts"
        return self._send_request(endpoint, use_jwt=False)

    def get_usd_spot_balance(self):
        """
        Returns total USD spot balance.
        """
        accounts_data = self.get_all_accounts()
        for acct in accounts_data.get("data", []):
            if acct.get("currency") == "USD":
                return float(acct.get("balance", {}).get("amount", 0))
        return 0.0

    # Example trading endpoint using JWT
    def place_order_jwt(self, order_payload):
        """
        Place a trade using Advanced JWT auth.
        """
        endpoint = "/v2/orders"
        return self._send_request(endpoint, method="POST", data=order_payload, use_jwt=True)


# === Helpers for nija_debug.py ===
def get_all_accounts():
    client = CoinbaseClient()
    return client.get_all_accounts()

def get_usd_spot_balance():
    client = CoinbaseClient()
    return client.get_usd_spot_balance()
