# nija_client.py
import os
import time
import hmac
import hashlib
import requests
import json

class CoinbaseClient:
    """
    Minimal Coinbase client that:
    - Reads COINBASE_API_KEY and COINBASE_API_SECRET (required)
    - Treats COINBASE_API_PASSPHRASE as optional (Advanced API / CDP may not need it)
    - Uses COINBASE_API_BASE (default https://api.coinbase.com)
    - get_accounts() tries sensible endpoints and returns:
        - None on unauthorized (401/403)
        - dict with keys ok/status/payload on error
        - JSON (dict/list) on success
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com").rstrip("/")

        if not self.api_key or not self.api_secret:
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

        # simple heuristic: if base contains 'cdp' we'll try platform endpoints first
        self.is_cdp = "cdp" in self.base_url

    def _sign_message(self, method, path, body=""):
        """
        Very simple HMAC signature compatible with classic Coinbase REST.
        For CDP/JWT flows you'd wire in the appropriate JWT logic; this function
        mirrors what the repo used to do (HMAC-SHA256).
        """
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def _get_headers(self, method, path, body=""):
        ts, sig = self._sign_message(method, path, body)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"
        }
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase
        return headers

    def _request(self, method, path, json_body=None):
        url = f"{self.base_url}{path}"
        body_text = ""
        if json_body is not None:
            body_text = json.dumps(json_body, separators=(",", ":"), ensure_ascii=False)
        headers = self._get_headers(method, path, body_text)
        resp = requests.request(method, url, headers=headers, json=json_body, timeout=10)
        return resp

    def get_accounts(self):
        """
        Try several endpoints gracefully:
         - /v2/accounts (classic)
         - /platform/v2/accounts (CDP)
         - /accounts (fallback)
        Returns:
         - None on unauthorized (401/403)
         - dict {ok:False, status:..., payload:...} on other non-200 results
         - parsed JSON (dict/list) on success
        """
        paths_to_try = ["/v2/accounts", "/platform/v2/accounts", "/accounts"]
        # if base looks like CDP, try platform first
        if self.is_cdp:
            paths_to_try = ["/platform/v2/accounts", "/v2/accounts", "/accounts"]

        last_exc = None
        for p in paths_to_try:
            try:
                resp = self._request("GET", p)
            except requests.RequestException as e:
                last_exc = e
                continue

            status = resp.status_code
            if status == 200:
                try:
                    return resp.json()
                except Exception:
                    return {"ok": True, "status": 200, "payload": resp.text}
            if status in (401, 403):
                # Unauthorized — caller should treat as auth failure
                return None
            # if 404 continue to next path
            if status == 404:
                # continue and try next candidate
                continue
            # other errors -> return structured result
            return {"ok": False, "status": status, "payload": resp.text}
        # if we get here, every path failed (connection errors or 404s)
        if last_exc:
            return {"ok": False, "status": None, "payload": f"request error: {str(last_exc)}"}
        return {"ok": False, "status": 404, "payload": "not found on attempted endpoints"}
