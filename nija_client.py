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
        return {"ok": False, "url": None, "status": 404, "payload": "No account endpoint found (all 404)"}
