# nija_client.py
import os
import time
import logging
import jwt
import requests

LOG = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s: %(message)s")


class CoinbaseClient:
    """
    Coinbase client supporting:
      - Advanced JWT (EC PEM private key) auth for Coinbase Advanced API
      - Classic (API key) fallback (note: full HMAC signing for classic mode is minimal here)
    """

    def __init__(self):
        LOG.info("🔍 Checking Coinbase credentials in environment...")

        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret_raw = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret_raw:
            raise RuntimeError("❌ Missing Coinbase API credentials (key or secret).")

        # Allow forcing the auth mode: "advanced" / "classic" / default auto
        forced_mode = os.getenv("COINBASE_AUTH_MODE", "").strip().lower()
        if forced_mode not in ("advanced", "classic", ""):
            LOG.warning("COINBASE_AUTH_MODE value '%s' not recognized. Falling back to auto-detect.", forced_mode)
            forced_mode = ""

        # Auto-fix PEM formatting if it looks like the EC private key is stored with literal \n
        if self.api_secret_raw and "\\n" in self.api_secret_raw:
            self.api_secret_raw = self.api_secret_raw.replace("\\n", "\n").strip()

        # Decide mode
        if forced_mode == "advanced":
            self.auth_mode = "advanced"
        elif forced_mode == "classic":
            self.auth_mode = "classic"
        else:
            self.auth_mode = self._detect_auth_mode()

        LOG.info("✅ CoinbaseClient initialized (%s mode).", self.auth_mode.title())

        # Optional preflight: don't crash the import flow — log failures
        try:
            LOG.info("ℹ️ Running preflight check...")
            _ = self.get_all_accounts()
            LOG.info("✅ Preflight check passed — Coinbase API reachable.")
        except Exception as e:
            LOG.warning("❌ Preflight check failed: %s", e)
            # Do not re-raise — allow the app to start even when preflight fails.

    def _detect_auth_mode(self):
        if self.api_secret_raw and "BEGIN EC PRIVATE KEY" in self.api_secret_raw:
            return "advanced"
        return "classic"

    # --- Advanced: sign with EC PEM private key (ES256) ---
    def _generate_jwt(self, method, endpoint, body=""):
        if not self.api_secret_raw:
            raise RuntimeError("❌ Missing PEM secret for JWT generation.")
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,  # short lived token
            "method": method.upper(),
            "request_path": endpoint,
            "body": body or ""
        }
        token = jwt.encode(payload, self.api_secret_raw, algorithm="ES256")
        return token

    def _headers(self, method, endpoint, body=""):
        if self.auth_mode == "advanced":
            token = self._generate_jwt(method, endpoint, body)
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        else:
            # Classic mode: basic headers (NOTE: full classic HMAC signing is not implemented here)
            return {
                "CB-ACCESS-KEY": self.api_key,
                "CB-VERSION": "2021-05-24",
                "Content-Type": "application/json",
            }

    def _send_request(self, endpoint, method="GET", body=""):
        url = self.base_url.rstrip("/") + endpoint
        headers = self._headers(method, endpoint, body)
        response = requests.request(method, url, headers=headers, data=body)
        if not response.ok:
            # bubble up useful info
            raise RuntimeError(f"❌ {response.status_code} {response.reason}: {response.text}")
        return response.json()

    # --- Account helpers ---
    def get_all_accounts(self):
        """
        Return the raw list of account dicts (the 'data' array from /v2/accounts).
        Raises RuntimeError on failure.
        """
        data = self._send_request("/v2/accounts")
        if not isinstance(data, dict) or "data" not in data:
            raise RuntimeError("❌ Unexpected response shape (missing 'data').")
        return data["data"]

    def get_usd_spot_balance(self):
        """
        Return USD spot balance as float. If no USD account found, returns 0.0.
        """
        accounts = self.get_all_accounts()
        for acct in accounts:
            # Coinbase v2 account dict sometimes uses 'balance' nested, sometimes keys differ.
            currency = acct.get("currency") or acct.get("balance", {}).get("currency")
            balance_amount = acct.get("balance", {}).get("amount") or acct.get("available", {}).get("amount") if isinstance(acct.get("available"), dict) else None
            if currency == "USD":
                try:
                    return float(balance_amount or 0.0)
                except Exception:
                    return 0.0
        return 0.0


# Module-level helper wrappers (backwards compatible with older nija_debug.py)
def _inst_client():
    """Internal: instantiate CoinbaseClient. Keeps instantiation local to avoid circular/import timing issues."""
    return CoinbaseClient()


def get_all_accounts():
    """
    Backwards-compatible wrapper that returns a list of account dicts.
    Example usage: from nija_client import get_all_accounts
    """
    client = _inst_client()
    return client.get_all_accounts()


def get_usd_spot_balance():
    """
    Backwards-compatible wrapper that returns the USD balance as float.
    Example usage: from nija_client import get_usd_spot_balance
    """
    client = _inst_client()
    return client.get_usd_spot_balance()


# Position sizing helper (exported)
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    """
    Calculates position size for a trade based on account equity.
      - account_equity : float
      - risk_factor    : float (percentage multiplier, e.g. 1.0 = 1% of account)
      - min_percent    : int (minimum percent of equity to trade)
      - max_percent    : int (maximum percent of equity to trade)
    returns : float : trade size in USD
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100.0)
    min_alloc = account_equity * (min_percent / 100.0)
    max_alloc = account_equity * (max_percent / 100.0)
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size


# explicit exports
__all__ = [
    "CoinbaseClient",
    "get_all_accounts",
    "get_usd_spot_balance",
    "calculate_position_size",
]
