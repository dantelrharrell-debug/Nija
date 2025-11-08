# nija_client.py
#!/usr/bin/env python3
"""
Robust Coinbase client helper for Nija bot.
Tries common Coinbase REST and Coinbase Advanced (CDP) endpoints
and prints useful diagnostics on failure.

Usage:
    from nija_client import CoinbaseClient
    c = CoinbaseClient()
    accounts = c.get_accounts()
"""

import os
import json
import requests
from typing import List, Optional

DEFAULT_REST_BASE = "https://api.coinbase.com"
DEFAULT_CDP_BASE = "https://api.cdp.coinbase.com"

def _norm_secret(s: Optional[str]) -> Optional[str]:
    """If secret contains literal '\n', convert to real newlines."""
    if not s:
        return s
    return s.replace("\\n", "\n") if "\\n" in s else s

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = _norm_secret(os.getenv("COINBASE_API_SECRET"))
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        self.base_url = os.getenv("COINBASE_API_BASE", "").strip() or DEFAULT_REST_BASE

        # Quick validation
        if not self.api_key or not self.api_secret:
            raise ValueError("Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment")

        # Common headers used for the simple REST-style auth paths we call.
        # NOTE: Advanced/CDP org-key auth sometimes uses JWT/PEM; this client will still attempt
        # the simple header approach and print the HTTP response for debugging.
        self.common_headers = {
            "Content-Type": "application/json",
            "CB-ACCESS-KEY": self.api_key,
        }
        if self.api_passphrase:
            self.common_headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase

        # friendly log
        print(f"Initializing CoinbaseClient (base_url={self.base_url})")

    def _request(self, method: str, path: str, headers=None, params=None, json_body=None, timeout=10):
        url = self.base_url.rstrip("/") + path
        hdrs = dict(self.common_headers)
        if headers:
            hdrs.update(headers)
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=hdrs, params=params, timeout=timeout)
            elif method.upper() == "POST":
                r = requests.post(url, headers=hdrs, json=json_body, timeout=timeout)
            else:
                raise ValueError("Unsupported method")
            # For debugging: always show response text on non-2xx to help diagnose endpoints/auth
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                return r.text
        except requests.exceptions.HTTPError as e:
            # Surface full status + truncated body
            body = ""
            try:
                body = e.response.text[:2000]
            except Exception:
                body = "<unavailable>"
            print(f"HTTP error during Coinbase request: {e.response.status_code} - {body}")
            raise
        except Exception as e:
            print(f"Network/Request exception while calling {url}: {e}")
            raise

    def get_accounts(self) -> List[dict]:
        """
        Attempts to fetch accounts using the most common endpoints:
         1) /v2/accounts   (standard Coinbase REST)
         2) /platform/v2/accounts  (Coinbase Advanced / CDP)
        Returns list of account dicts or raises.
        """
        tried = []
        # preferred order
        candidate_paths = ["/v2/accounts", "/platform/v2/accounts", "/accounts"]
        last_exc = None
        for p in candidate_paths:
            try:
                print(f"Fetching accounts from {self.base_url}{p}")
                resp = self._request("GET", p)
                # many Coinbase endpoints wrap data in {"data": [...]}
                if isinstance(resp, dict) and "data" in resp and isinstance(resp["data"], list):
                    return resp["data"]
                # sometimes the API returns a top-level list
                if isinstance(resp, list):
                    return resp
                # sometimes returns an object with "accounts" key
                if isinstance(resp, dict) and "accounts" in resp and isinstance(resp["accounts"], list):
                    return resp["accounts"]
                # otherwise return raw resp inside list for inspection
                return [resp]
            except Exception as e:
                last_exc = e
                tried.append(p)
                # try next candidate
        # If we reach here, all endpoints failed
        print(f"All candidate account endpoints failed: tried {tried}")
        if last_exc:
            raise last_exc
        return []

    def get_primary_account(self) -> Optional[dict]:
        """Return the first account marked primary if available."""
        accts = self.get_accounts()
        for a in accts:
            if isinstance(a, dict) and a.get("primary"):
                return a
        return accts[0] if accts else None

    def submit_order(self, *args, **kwargs):
        """
        Placeholder helper for submitting orders.
        Real implementation depends on the API (Advanced / REST / JWT). Keep as stub until
        you choose the API path and auth method.
        """
        raise NotImplementedError("Order submission not implemented in this helper. Use nija_coinbase_* helpers.")

if __name__ == "__main__":
    # quick local smoke test
    c = CoinbaseClient()
    try:
        accts = c.get_accounts()
        if not accts:
            print("No accounts returned (empty). Check API permissions and IP allowlist.")
        else:
            print("Accounts (first 10):")
            for i, a in enumerate(accts[:10]):
                if isinstance(a, dict):
                    name = a.get("name", "<unknown>")
                    bal = a.get("balance", {})
                    print(f" {i+1}. {name}: {bal.get('amount','?')} {bal.get('currency','?')} (primary={a.get('primary')})")
                else:
                    print(f" {i+1}. {a}")
    except Exception as e:
        print("Error fetching accounts:", e)
