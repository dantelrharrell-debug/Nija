"""
Lightweight Coinbase HTTP client for NIJA.
No coinbase-advanced-py dependency required.
Provides:
 - get_accounts()
 - get_usd_balance()
 - client (simple wrapper)
"""

import os
import time
import base64
import hmac
import hashlib
import logging
import requests

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# Environment vars (Railway/Render should already have these)
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")  # base64 encoded secret from Coinbase
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")  # default

if not (API_KEY and API_SECRET and API_PASSPHRASE):
    logger.error("Missing Coinbase API credentials in environment variables.")
    raise RuntimeError("Missing Coinbase API credentials")

# Helper: create CB signature
def _make_signature(method: str, request_path: str, body: str = "") -> (str, str):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + request_path + (body or "")
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception as e:
        logger.error("Failed to base64-decode API secret: %s", e)
        raise
    digest = hmac.new(secret_bytes, prehash.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    return signature, ts

# Low-level request
def _cb_request(method: str, path: str, body: str = "") -> requests.Response:
    signature, ts = _make_signature(method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json",
        "CB-VERSION": "2025-11-02",
    }
    url = API_BASE.rstrip("/") + path
    logger.debug("Coinbase request %s %s", method, url)
    resp = requests.request(method, url, headers=headers, data=body, timeout=15)
    return resp

# Public functions
def get_accounts():
    """
    Returns the raw JSON response for /v2/accounts (or raises on error).
    """
    path = "/v2/accounts"
    resp = _cb_request("GET", path, "")
    if resp.status_code != 200:
        logger.error("get_accounts failed: HTTP %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Coinbase API get_accounts failed: {resp.status_code} {resp.text}")
    return resp.json()

def get_usd_balance():
    """
    Returns the USD amount (as string) for Spot USD if present, else "0".
    Strategy:
      - Inspect all accounts returned by /v2/accounts
      - Prefer account with currency == "USD" and type == "fiat" or name contains "Spot"
      - Fallback: first currency=="USD"
    """
    data = get_accounts()
    for acct in data.get("data", []):
        currency = acct.get("currency") or acct.get("balance", {}).get("currency")
        name = acct.get("name", "") or acct.get("type", "")
        bal = acct.get("balance", {}) or {}
        amount = bal.get("amount", "0")
        # Heuristics: prefer Spot / fiat accounts named Spot or with type 'fiat'
        if currency == "USD" and ("spot" in name.lower() or acct.get("type","").lower() == "fiat"):
            logger.info("Found USD Spot (preferred): %s %s", name, amount)
            return amount
    # fallback: any USD account
    for acct in data.get("data", []):
        currency = acct.get("currency") or acct.get("balance", {}).get("currency")
        bal = acct.get("balance", {}) or {}
        amount = bal.get("amount", "0")
        if currency == "USD":
            logger.info("Found USD account (fallback): %s %s", acct.get("name"), amount)
            return amount
    logger.info("No USD account found; returning 0")
    return "0"

# Simple wrapper object for compatibility with the rest of your code
class SimpleCoinbaseClient:
    def __init__(self):
        self.api_key = API_KEY

    def get_accounts(self):
        return get_accounts()

    def get_account_balance(self, currency="USD"):
        # return numeric or string amount to match your previous API
        return get_usd_balance()

# Exported client for importers expecting 'client'
client = SimpleCoinbaseClient()
# Convenience function for nija_preflight import compatibility
def fetch_usd_balance():
    return client.get_account_balance("USD")

# If run directly, print accounts and usd balance
if __name__ == "__main__":
    try:
        accounts = get_accounts()
        print("Accounts returned:", len(accounts.get("data", [])))
        for a in accounts.get("data", []):
            print(a.get("name"), a.get("currency") or a.get("balance",{}).get("currency"), a.get("balance"))
        print("USD balance (get_usd_balance):", get_usd_balance())
    except Exception as e:
        logger.exception("Error when querying Coinbase: %s", e)
        raise
