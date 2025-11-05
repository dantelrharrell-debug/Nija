import os
import requests
import logging

log = logging.getLogger("nija_client")
BASE_URL = "https://api.coinbase.com"

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")

        self.auth_method = None
        self._detect_auth_method()

    def _detect_auth_method(self):
        """
        Auto-detect whether JWT or Classic API key works.
        """
        if self.api_key and self.api_secret:
            log.info("⚠️ Trying Advanced JWT key...")
            if self._test_jwt():
                self.auth_method = "JWT"
                log.info("✅ Advanced JWT key accepted.")
                return
            log.warning("⚠️ JWT failed, will try Classic API key if passphrase provided.")

        if self.api_key and self.api_secret and self.passphrase:
            log.info("⚠️ Trying Classic API key...")
            if self._test_classic():
                self.auth_method = "CLASSIC"
                log.info("✅ Classic API key accepted.")
                return

        raise RuntimeError("❌ No valid Coinbase credentials detected.")

    def _test_jwt(self):
        try:
            headers = {"Authorization": f"Bearer {self.api_secret}"}
            r = requests.get(f"{BASE_URL}/v2/accounts", headers=headers)
            return r.status_code == 200
        except Exception:
            return False

    def _test_classic(self):
        try:
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "CB-ACCESS-SIGN": "dummy",
                "CB-ACCESS-TIMESTAMP": "0",
            }
            r = requests.get(f"{BASE_URL}/v2/accounts", headers=headers)
            return r.status_code == 200
        except Exception:
            return False

    def _send_request(self, endpoint, method="GET", data=None):
        if self.auth_method == "JWT":
            headers = {"Authorization": f"Bearer {self.api_secret}"}
        elif self.auth_method == "CLASSIC":
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "CB-ACCESS-SIGN": "dummy",
                "CB-ACCESS-TIMESTAMP": "0",
            }
        else:
            raise RuntimeError("❌ No valid auth method set.")

        url = f"{BASE_URL}{endpoint}"
        r = requests.request(method, url, headers=headers, json=data)
        if r.status_code != 200:
            raise RuntimeError(f"❌ Request failed: {r.status_code} {r.text}")
        return r.json()

    def get_all_accounts(self):
        return self._send_request("/v2/accounts")["data"]

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for a in accounts:
            if a["currency"] == "USD":
                return float(a["balance"]["amount"])
        return 0.0

    def calculate_position_size(
        self, account_equity, risk_factor=1.0, min_percent=2, max_percent=10
    ):
        """
        Calculates position size for a trade based on account equity.

        account_equity : float : USD account balance
        risk_factor    : float : Multiplier for trade confidence (default=1.0)
        min_percent    : int   : Minimum % of equity to trade
        max_percent    : int   : Maximum % of equity to trade

        returns : float : Trade size in USD
        """
        if account_equity <= 0:
            raise ValueError("Account equity must be greater than 0 to trade.")

        raw_allocation = account_equity * (risk_factor / 100)

        # Clamp allocation between min and max percent
        min_alloc = account_equity * (min_percent / 100)
        max_alloc = account_equity * (max_percent / 100)

        trade_size = max(min_alloc, min(raw_allocation, max_alloc))
        return trade_size
