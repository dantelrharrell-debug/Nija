import os
import time
import hmac
import hashlib
import requests
import logging

log = logging.getLogger("nija_client")
log.setLevel(logging.INFO)

BASE_URL = "https://api.coinbase.com"

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional
        self.mode = None  # 'classic' or 'jwt'

        # Try auto-detect mode
        if self._test_classic_api():
            self.mode = "classic"
            log.info("✅ Using Classic API Key + Passphrase mode")
        elif self._test_jwt_api():
            self.mode = "jwt"
            log.info("✅ Using Advanced JWT mode")
        else:
            raise RuntimeError("❌ No working Coinbase API method found. Check key permissions.")

    # ==================== Auto-detect helpers ====================
    def _test_classic_api(self):
        if not self.passphrase:
            return False
        try:
            self._send_request("/v2/accounts", use_jwt=False)
            return True
        except:
            return False

    def _test_jwt_api(self):
        try:
            self._send_request("/v2/accounts", use_jwt=True)
            return True
        except:
            return False

    # ==================== Request helper ====================
    def _send_request(self, endpoint, use_jwt=None):
        """use_jwt: True forces JWT, False forces Classic, None uses auto-detected mode"""
        if use_jwt is None:
            use_jwt = (self.mode == "jwt")

        headers = {"CB-VERSION": "2025-11-05"}
        if use_jwt:
            headers["Authorization"] = f"Bearer {self.api_secret}"
        else:
            timestamp = str(int(time.time()))
            method = "GET"
            body = ""
            message = timestamp + method + endpoint + body
            signature = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
            headers.update({
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
            })

        r = requests.get(BASE_URL + endpoint, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"❌ Request failed: {r.status_code} {r.text[:200]}")
        return r.json()

    # ==================== Public methods ====================
    def get_all_accounts(self):
        return self._send_request("/v2/accounts")["data"]

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for a in accounts:
            if a["currency"] == "USD":
                return float(a["balance"]["amount"])
        return 0.0
