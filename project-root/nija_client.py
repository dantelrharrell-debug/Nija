# nija_client.py
"""Robust Coinbase client - tries Coinbase Advanced (CDP) endpoint first,
then falls back to classic /v2 endpoints. Passphrase optional.
Also exposes calculate_position_size as a small utility to avoid import errors.
"""
import os
import time
import hmac
import hashlib
import requests
from typing import Optional, Dict, Any

# If you want to switch base URL explicitly, set COINBASE_API_BASE in .env
# Recommended for Advanced CDP: https://api.cdp.coinbase.com
DEFAULT_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Optional for Advanced API
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        self.base = DEFAULT_BASE.rstrip("/")

        if not all([self.api_key, self.api_secret]):
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set in environment")

    def _make_signature(self, method: str, path: str, body: str = "") -> Dict[str,str]:
        """Simple HMAC style signature used by some Coinbase endpoints.
        For CDP / advanced endpoints you may need JWT/auth that differs; this
        function keeps the existing HMAC approach for compatibility where used.
        """
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        sign = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sign,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase
        return headers

    def _request(self, method: str, url: str, path_for_sign: str, **kwargs) -> requests.Response:
        headers = self._make_signature(method.upper(), path_for_sign, kwargs.get("data", "") or "")
        # Merge user-provided headers if present
        extra = kwargs.pop("headers", {})
        headers.update(extra)
        resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
        return resp

    def get_accounts(self) -> Optional[Dict[str, Any]]:
        """Try Advanced/CDP path first, then fallback to classic /v2/accounts.
        Returns JSON dict or None on unrecoverable error.
        """
        # Candidate endpoints (ordered)
        candidates = [
            (f"{self.base}/platform/v2/accounts", "/platform/v2/accounts"),  # CDP/Advanced
            (f"{self.base}/platform/v1/accounts", "/platform/v1/accounts"),  # older CDP variant
            ("https://api.coinbase.com/v2/accounts", "/v2/accounts"),        # public Coinbase REST
            ("https://api.coinbase.com/accounts", "/accounts"),             # sometimes used by libs
        ]

        last_err = None
        for url, sign_path in candidates:
            try:
                resp = self._request("GET", url, sign_path)
            except requests.exceptions.RequestException as e:
                last_err = e
                # network issue or DNS; try next URL
                continue

            # Successful 200
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return {"status_code": resp.status_code, "text": resp.text}

            # handle common expected failures gracefully
            if resp.status_code in (401, 403):
                # unauthorized - API key or permissions problem
                print(f"❌ Coinbase unauthorized ({resp.status_code}) when calling {url} — check API key type & permissions.")
                return None
            if resp.status_code == 404:
                # endpoint not present on this base; try next candidate
                last_err = f"404 when calling {url}"
                continue
            # Other status codes: show body and stop
            print(f"❌ Error fetching accounts from {url}: {resp.status_code} {resp.text}")
            last_err = f"{resp.status_code} {resp.text}"
            # try next just in case
        # If we got here, none of the endpoints worked
        print("❌ All account endpoints failed. Last error:", last_err)
        return None

# Small helper exported because other modules import it
def calculate_position_size(account_balance: float, risk_pct: float = 0.02) -> float:
    """
    Minimal stub to satisfy imports and give a basic position size calc.
    account_balance: total account equity in quote (e.g. USD)
    risk_pct: fraction of account to risk per trade (0.02 = 2%)
    Returns dollar allocation (positive float).
    """
    try:
        alloc = float(account_balance) * float(risk_pct)
        return max(0.0, alloc)
    except Exception:
        return 0.0
