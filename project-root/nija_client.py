# nija_client.py
"""
Robust Coinbase client wrapper for Nija.
- Passphrase is optional (Advanced/CDP API).
- Tries common account endpoints in this order:
    1) /platform/v2/accounts       (CDP)
    2) /v2/accounts               (classic REST v2)
    3) /accounts                  (legacy)
- Returns (url_tried, status_code, json_or_text)
- Does not throw on 401/404 — returns info for health/debugging.
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests

# small helper so other modules that import this file don't break
def calculate_position_size(*args, **kwargs):
    """Stub placeholder for compatibility. Replace with real position sizing."""
    # Minimal deterministic stub so imports don't break.
    return 0

class CoinbaseClient:
    def __init__(self):
        # Required: API key and secret
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Optional passphrase for legacy REST keys (not required for Advanced/CDP)
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        # Optional custom base (set this to CDP base if using Coinbase Advanced)
        self.base = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        # The CDP host sometimes uses api.cdp.coinbase.com or api.cdp.coinbase.com/platform/v2
        # but we'll rely on base + path below.

        if not self.api_key or not self.api_secret:
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set in environment")

    def _sign(self, timestamp, method, path, body=""):
        """
        Create Coinbase-style HMAC signature.
        Uses base64 of HMAC-SHA256 as is commonly accepted.
        """
        message = f"{timestamp}{method}{path}{body}"
        h = hmac.new(self.api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(h.digest()).decode()

    def _get_headers(self, method, path, body=""):
        ts = str(int(time.time()))
        signature = self._sign(ts, method, path, body)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
            "User-Agent": "nija-trader/1.0"
        }
        # only include passphrase if provided
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase
        return headers

    def _try_get(self, url, method="GET", path="/", body=""):
        """
        Performs a requests call and returns (url, status_code, parsed_json_or_text).
        Does not raise, caller will inspect status code.
        """
        try:
            headers = self._get_headers(method, path, body)
            response = requests.request(method, url, headers=headers, data=body, timeout=15)
            status = response.status_code
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            return (url, status, payload, response)
        except requests.exceptions.RequestException as e:
            return (url, None, {"error": str(e)}, None)

    def get_accounts(self):
        """
        Try CDP -> v2 -> legacy endpoints.
        Returns a dict:
        {
            "ok": bool,
            "url": string,
            "status": int or None,
            "payload": dict or text,
        }
        """
        candidates = [
            (f"{self.base.rstrip('/')}/platform/v2/accounts", "/platform/v2/accounts"),
            (f"{self.base.rstrip('/')}/v2/accounts", "/v2/accounts"),
            (f"{self.base.rstrip('/')}/accounts", "/accounts"),
        ]

        for full_url, path in candidates:
            url, status, payload, response_obj = self._try_get(full_url, "GET", path, "")
            # Log status locally by returning it — caller will print/log
            if status and status >= 200 and status < 300:
                return {"ok": True, "url": full_url, "status": status, "payload": payload}
            # If 401 or 403 return immediately with helpful message (unauthorized)
            if status in (401, 403):
                return {"ok": False, "url": full_url, "status": status, "payload": payload}
            # If 404, try next candidate
            if status == 404:
                # continue trying
                continue
            # if status is None (request exception) return details
            if status is None:
                return {"ok": False, "url": full_url, "status": status, "payload": payload}
            # other non-2xx — return so caller can see body
            if status and (status < 200 or status >= 300):
                return {"ok": False, "url": full_url, "status": status, "payload": payload}

        # no candidate succeeded (all 404 or equiv)
        return {"ok": False, "url": None, "status": 404, "payload": "No account endpoint found (all 404)"}# nija_client.py
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
