import os
import time
import hmac
import hashlib
import base64
import requests
import logging
import jwt  # PyJWT

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)


class CoinbaseClient:
    def __init__(self):
        # Load env variables
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # None if JWT
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # Determine if we're using JWT
        self.use_jwt = self.passphrase is None
        if self.use_jwt:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        else:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _get_jwt_header(self, method, path, body=""):
        """Generate JWT token for Advanced API key"""
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 300,  # 5 minutes
            "sub": self.api_key,
            "path": path,
            "method": method.upper(),
            "body": body,
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    def _get_standard_headers(self, method, path, body=""):
        """Generate headers for standard API key"""
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

    def _send_request(self, endpoint, method="GET", body="", use_jwt=None):
        """Send request using JWT or standard API key depending on availability"""
        url = self.base_url + endpoint
        use_jwt = self.use_jwt if use_jwt is None else use_jwt

        headers = self._get_jwt_header(method, endpoint, body) if use_jwt else self._get_standard_headers(method, endpoint, body)

        response = requests.request(method, url, headers=headers, data=body)
        if response.status_code == 401:
            raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
        if response.status_code == 404:
            raise RuntimeError(f"❌ Request failed: 404 {response.text}")
        if not response.ok:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    # --- Helpers for nija_debug.py ---
    def get_all_accounts(self):
        """Return all accounts"""
        if self.use_jwt:
            # JWT may not support this endpoint
            try:
                return self._send_request("/v2/accounts")
            except RuntimeError as e:
                log.error(f"❌ JWT cannot access /accounts endpoint: {e}")
                return None
        return self._send_request("/v2/accounts")

    def get_usd_spot_balance(self):
        """Return USD balance from accounts"""
        accounts_data = self.get_all_accounts()
        if accounts_data is None:
            return None
        for acc in accounts_data.get("data", []):
            if acc.get("currency") == "USD":
                return float(acc.get("balance", {}).get("amount", 0))
        return 0.0


# Global client for helpers
client = CoinbaseClient()


# --- Helper functions for nija_debug.py ---
def get_all_accounts():
    return client.get_all_accounts()


def get_usd_spot_balance():
    return client.get_usd_spot_balance()
