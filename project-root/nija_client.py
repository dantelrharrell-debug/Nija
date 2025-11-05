# nija_client.py
import os
import time
import logging
import requests
import jwt
import hashlib
import hmac
import base64
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        # Fetch credentials from environment
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Missing Coinbase API credentials")

        if self.passphrase:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")
            self.use_jwt = False
        else:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
            self.use_jwt = True

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _jwt_headers(self, method, path, body=""):
        """Generate JWT headers for Advanced API keys"""
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{body}"
        secret_bytes = base64.b64decode(self.api_secret)
        signature = hmac.new(secret_bytes, message.encode(), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-VERSION": "2025-11-05",
            "Content-Type": "application/json"
        }

    def _classic_headers(self, method, path, body=""):
        """Classic API headers (with passphrase)"""
        timestamp = str(int(time.time()))
        body = body or ""
        message = f"{timestamp}{method.upper()}{path}{body}"
        secret_bytes = self.api_secret.encode()
        signature = hmac.new(secret_bytes, message.encode(), hashlib.sha256).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def _send_request(self, endpoint, method="GET", body="", max_retries=3):
        url = f"{self.base_url}{endpoint}"
        for attempt in range(1, max_retries + 1):
            try:
                headers = self._jwt_headers(method, endpoint, body) if self.use_jwt else self._classic_headers(method, endpoint, body)
                response = requests.request(method, url, headers=headers, data=body)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    log.error("❌ 401 Unauthorized. Check API key permissions and JWT usage.")
                    if self.use_jwt and self.passphrase:
                        # Fall back to classic API automatically
                        log.info("⚠️ Switching to Classic API key + passphrase...")
                        self.use_jwt = False
                        continue
                    else:
                        raise RuntimeError(f"❌ 401 Unauthorized: {response.text}")
                else:
                    log.warning(f"⚠️ Request failed (attempt {attempt}): {response.status_code} {response.text}")
                    time.sleep(2 ** attempt)
            except Exception as e:
                log.warning(f"⚠️ Exception on attempt {attempt}: {e}")
                time.sleep(2 ** attempt)
        raise RuntimeError(f"❌ Request failed after {max_retries} attempts: {response.status_code} {response.text}")

    def get_all_accounts(self):
        """Fetch all Coinbase accounts"""
        endpoint = "/v2/accounts"
        data = self._send_request(endpoint)
        return data.get("data", [])

    def get_usd_spot_balance(self):
        """Return total USD spot balance"""
        accounts = self.get_all_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return float(acc.get("balance", {}).get("amount", 0))
        return 0.0


# Helper functions for nija_debug.py
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
