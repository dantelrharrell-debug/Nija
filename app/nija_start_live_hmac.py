# nija_hmac_client.py
"""
Minimal HMAC client shim for Coinbase-style API.
Drop this file in the repo root (/app) so your startup script can import it.
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
from typing import Tuple, Any

class CoinbaseClient:
    def __init__(self):
        # Environment variables expected by this shim
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Retail API base by default; change COINBASE_API_BASE if needed
        self.base = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        if not (self.api_key and self.api_secret):
            # Do NOT raise here; allow the startup script to log env issues gracefully.
            pass

    def _sign(self, method: str, path: str, body: str = "") -> Tuple[str,str]:
        ts = str(int(time.time()))
        message = ts + method.upper() + path + (body or "")
        # Coinbase retail HMAC uses base64-encoded HMAC-SHA256 of message with secret (binary)
        h = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
        sig = base64.b64encode(h).decode()
        return ts, sig

    def request(self, method: str, path: str, data: Any = None) -> Tuple[int, Any]:
        """
        method: "GET"/"POST"/etc
        path: API path starting with /
        data: python object to JSON-encode for body or None
        returns: (status_code, parsed_json_or_text)
        """
        if not self.api_key or not self.api_secret:
            return 0, {"error": "Missing COINBASE_API_KEY or COINBASE_API_SECRET"}

        body = json.dumps(data) if data is not None else ""
        ts, sig = self._sign(method, path, body)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        url = self.base.rstrip("/") + path
        try:
            resp = requests.request(method, url, headers=headers, data=body if body else None, timeout=15)
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, resp.text
        except Exception as e:
            return 0, {"error": str(e)}
