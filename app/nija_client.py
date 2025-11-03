#!/usr/bin/env python3
"""
NIJA Coinbase Advanced Trade tester
- Uses plain-text API secret
- Prints accounts and USD Spot balance
- Works with funded Spot wallet
"""

import os, time, hmac, hashlib, logging, requests, json, base64

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.exchange.coinbase.com")

if not (API_KEY and API_SECRET and API_PASSPHRASE):
    logger.error("Missing Coinbase API credentials in environment variables.")
    raise RuntimeError("Missing Coinbase API credentials")

def _make_signature(method: str, path: str, body: str = ""):
    """Generate HMAC SHA256 signature for Advanced Trade REST API"""
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + (body or "")
    secret_bytes = API_SECRET.encode("utf-8")  # plain-text secret
    digest = hmac.new(secret_bytes, prehash.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    return signature, ts

def _cb_request(method: str, path: str, body: str = ""):
    """Send HTTP request to Coinbase Advanced Trade REST API"""
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

def get_accounts():
    """Fetch all accounts"""
    resp = _cb_request("GET", "/accounts", "")
    if resp.status_code != 200:
        logger.error("Coinbase API error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Coinbase API returned {resp.status_code}: {resp.text}")
    return resp.json().get("data", [])

def get_usd_spot_balance():
    """Return USD Spot balance and account details"""
    accounts = get_accounts()
    for acct in accounts:
        currency = acct.get("currency")
        name = (acct.get("name") or "").lower()
        typ = (acct.get("type") or "").lower()
        bal = acct.get("balance", {}).get("amount", "0")
        if currency == "USD" and ("spot" in name or typ == "fiat"):
            return bal, acct
    # fallback: any USD
    for acct in accounts:
        currency = acct.get("currency")
        bal = acct.get("balance", {}).get("amount", "0")
        if currency == "USD":
            return bal, acct
    return "0", None

if __name__ == "__main__":
    try:
        accounts = get_accounts()
        logger.info(f"Total accounts returned: {len(accounts)}")
        for a in accounts:
            name = a.get("name")
            cur = a.get("currency")
            bal = a.get("balance", {}).get("amount")
            logger.info(f"- {name:30} {cur:6} {bal}")
        usd_amt, acct = get_usd_spot_balance()
        if acct:
            logger.info(f"\nDetected USD Spot balance: {usd_amt}, account: {acct.get('name')}, id: {acct.get('id')}")
        else:
            logger.info("\nNo USD Spot balance detected.")
    except Exception as e:
        logger.exception("Error: %s", e)
        raise
