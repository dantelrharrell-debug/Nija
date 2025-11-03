#!/usr/bin/env python3
"""
NIJA Coinbase REST client using plain-text API secret.
Detects USD Spot balance and prepares bot for live trading.
"""

import os, time, hmac, hashlib, logging, requests, base64
from dotenv import load_dotenv

# Load .env if present (for local testing)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not (API_KEY and API_SECRET and API_PASSPHRASE):
    logger.error("Missing Coinbase API credentials in environment variables.")
    raise RuntimeError("Missing Coinbase API credentials")

def _make_signature(method: str, path: str, body: str = ""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + (body or "")
    secret_bytes = API_SECRET.encode()  # plain-text secret
    digest = hmac.new(secret_bytes, prehash.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    return signature, ts

def _cb_request(method: str, path: str, body: str = ""):
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
    resp = requests.request(method, url, headers=headers, data=body, timeout=15)
    return resp

def get_usd_spot_balance():
    resp = _cb_request("GET", "/v2/accounts", "")
    if resp.status_code != 200:
        logger.error("Coinbase API error %s: %s", resp.status_code, resp.text)
        return "0", None
    data = resp.json().get("data", [])
    for acct in data:
        currency = acct.get("currency") or acct.get("balance", {}).get("currency")
        name = (acct.get("name") or "").lower()
        typ = (acct.get("type") or "").lower()
        bal = acct.get("balance") or {}
        amt = bal.get("amount", "0")
        if currency == "USD" and ("spot" in name or typ == "fiat"):
            return amt, acct
    # fallback any USD
    for acct in data:
        currency = acct.get("currency") or acct.get("balance", {}).get("currency")
        bal = acct.get("balance") or {}
        amt = bal.get("amount", "0")
        if currency == "USD":
            return amt, acct
    return "0", None

# Quick test if run standalone
if __name__ == "__main__":
    amt, acct = get_usd_spot_balance()
    if acct:
        logger.info(f"Detected USD Spot balance: {amt}, account: {acct.get('name')}, id: {acct.get('id')}")
    else:
        logger.info("No USD Spot balance detected.")
