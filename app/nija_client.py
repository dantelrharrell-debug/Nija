# nija_client.py
"""
Drop-in Coinbase client for Nija debug scripts.

Provides:
 - CoinbaseClient class
 - module-level wrappers: get_all_accounts(), get_usd_spot_balance()
 - calculate_position_size()
Designed to be import-safe for nija_debug.py:
    from nija_client import CoinbaseClient, calculate_position_size, get_usd_spot_balance, get_all_accounts
"""

import os
import time
import logging
import jwt
import requests

LOG = logging.getLogger("nija_client")
if not LOG.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s: %(message)s")


class CoinbaseClient:
    def __init__(self):
        LOG.info("🔍 Checking Coinbase credentials in environment...")

        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret_raw = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret_raw:
            raise RuntimeError("❌ Missing Coinbase API credentials (COINBASE_API_KEY or COINBASE_API_SECRET).")

        # Fix common PEM encoding (literal "\n" -> actual newline)
        if "\\n" in (self.api_secret_raw or ""):
            self.api_secret_raw = self.api_secret_raw.replace("\\n", "\n").strip()

        # detect mode
        self.auth_mode = "advanced" if "BEGIN EC PRIVATE KEY" in (self.api_secret_raw or "") else "classic"
        LOG.info("✅ CoinbaseClient initialized (%s mode).", self.auth_mode)

        # preflight check (log only; do not raise)
        try:
            LOG.info("ℹ️ Running preflight check...")
            _ = self.get_all_accounts()  # instance method (no module-level wrapper)
            LOG.info("✅ Preflight check succeeded.")
        except Exception as e:
            LOG.warning("❌ Preflight check failed: %s", e)

    # --- Advanced JWT generation (EC private key) ---
    def _generate_jwt(self, method, endpoint, body=""):
        if not self.api_secret_raw:
            raise RuntimeError("Missing PEM secret for JWT generation.")
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,
            "method": method.upper(),
            "request_path": endpoint,
            "body": body or ""
        }
        token = jwt.encode(payload, self.api_secret_raw, algorithm="ES256")
        return token

    def _headers(self, method, endpoint, body=""):
        if self.auth_mode == "advanced":
            token = self._generate_jwt(method, endpoint, body)
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        else:
            # Classic mode: basic headers (NOTE: full CB classic HMAC signing not implemented here)
            return {"CB-ACCESS-KEY": self.api_key, "CB-VERSION": "2021-05-24", "Content-Type": "application/json"}

    def _send_request(self, endpoint, method="GET", body=""):
        url = self.base_url.rstrip("/") + endpoint
        headers = self._headers(method, endpoint, body)
        resp = requests.request(method, url, headers=headers, data=body, timeout=15)
        if not resp.ok:
            raise RuntimeError(f"❌ {resp.status_code} {resp.reason}: {resp.text}")
        return resp.json()

    def get_all_accounts(self):
        """Return list of account dicts (the 'data' from /v2/accounts)."""
        resp = self._send_request("/v2/accounts")
        if not isinstance(resp, dict) or "data" not in resp:
            raise RuntimeError("Unexpected response shape (missing 'data').")
        return resp["data"]

    def get_usd_spot_balance(self):
        """Return USD balance as float; returns 0.0 if none."""
        accounts = self.get_all_accounts()
        for acct in accounts:
            # Coinbase account dicts vary; check common paths
            currency = acct.get("currency") or acct.get("balance", {}).get("currency")
            amount = acct.get("balance", {}).get("amount") or acct.get("available", {}).get("amount") if isinstance(acct.get("available"), dict) else None
            if currency == "USD":
                try:
                    return float(amount or 0.0)
                except Exception:
                    return 0.0
        return 0.0


# ---------------------------
# Module-level wrappers
# ---------------------------
def _inst_client():
    """Create a fresh client instance on demand (avoids circular import timing)."""
    return CoinbaseClient()


def get_all_accounts():
    """Backwards-compatible wrapper used by nija_debug.py"""
    client = _inst_client()
    return client.get_all_accounts()


def get_usd_spot_balance():
    """Backwards-compatible wrapper used by nija_debug.py"""
    client = _inst_client()
    return client.get_usd_spot_balance()


# ---------------------------
# Position sizing helper
# ---------------------------
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100.0)
    min_alloc = account_equity * (min_percent / 100.0)
    max_alloc = account_equity * (max_percent / 100.0)
    return max(min_alloc, min(raw_allocation, max_alloc))


# explicit exports for `from nija_client import ...`
__all__ = [
    "CoinbaseClient",
    "get_all_accounts",
    "get_usd_spot_balance",
    "calculate_position_size",
]
