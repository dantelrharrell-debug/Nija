# nija_client.py - minimal, import-safe replacement
import os
import time
import logging
import jwt
import requests

LOG = logging.getLogger("nija_client")
if not LOG.handlers:
    logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self):
        LOG.info("🔍 Checking Coinbase credentials in environment...")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not (self.api_key and self.api_secret):
            raise RuntimeError("❌ Missing Coinbase API credentials (COINBASE_API_KEY or COINBASE_API_SECRET)")

        # Fix PEM if user stored with literal '\n'
        if isinstance(self.api_secret, str) and "\\n" in self.api_secret:
            self.api_secret = self.api_secret.replace("\\n", "\n").strip()

        self.mode = "advanced" if "BEGIN EC PRIVATE KEY" in (self.api_secret or "") else "classic"
        LOG.info("✅ CoinbaseClient initialized (%s mode).", self.mode)

    def _generate_jwt(self, method, endpoint, body=""):
        payload = {"iat": int(time.time()), "exp": int(time.time()) + 120,
                   "method": method.upper(), "request_path": endpoint, "body": body or ""}
        return jwt.encode(payload, self.api_secret, algorithm="ES256")

    def _headers(self, method, endpoint, body=""):
        if self.mode == "advanced":
            token = self._generate_jwt(method, endpoint, body)
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        else:
            return {"CB-ACCESS-KEY": self.api_key, "CB-VERSION": "2021-05-24", "Content-Type": "application/json"}

    def _send_request(self, endpoint, method="GET", body=""):
        url = self.base_url.rstrip("/") + endpoint
        headers = self._headers(method, endpoint, body)
        resp = requests.request(method, url, headers=headers, data=body, timeout=15)
        if not resp.ok:
            raise RuntimeError(f"❌ {resp.status_code} {resp.reason}: {resp.text}")
        return resp.json()

    def get_all_accounts(self):
        resp = self._send_request("/v2/accounts")
        if not isinstance(resp, dict) or "data" not in resp:
            raise RuntimeError("Unexpected response shape (missing 'data').")
        return resp["data"]

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for acct in accounts:
            # Support common shapes
            currency = acct.get("currency") or acct.get("balance", {}).get("currency")
            amount = acct.get("balance", {}).get("amount") if acct.get("balance") else None
            if currency == "USD":
                try:
                    return float(amount or 0.0)
                except Exception:
                    return 0.0
        return 0.0

def _inst_client():
    return CoinbaseClient()

# Backwards-compatible module-level helpers
def get_all_accounts():
    return _inst_client().get_all_accounts()

def get_usd_spot_balance():
    return _inst_client().get_usd_spot_balance()

def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100.0)
    min_alloc = account_equity * (min_percent / 100.0)
    max_alloc = account_equity * (max_percent / 100.0)
    return max(min_alloc, min(raw_allocation, max_alloc))

__all__ = ["CoinbaseClient", "get_all_accounts", "get_usd_spot_balance", "calculate_position_size"]
