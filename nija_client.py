#!/usr/bin/env python3
"""
NIJA Client: Coinbase Advanced ECDSA API
Handles authentication, signing, and USD Spot balance fetching.
"""

import os
import time
import json
import base64
import logging
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

# --- Load environment variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    log.error("Missing Coinbase credentials. Set COINBASE_API_KEY and COINBASE_API_SECRET")
    raise RuntimeError("Coinbase credentials missing")

# Convert single-line escaped key to proper PEM
if "\\n" in API_SECRET:
    API_SECRET = API_SECRET.replace("\\n", "\n")

# Load private key
try:
    _PRIVATE_KEY = load_pem_private_key(API_SECRET.encode(), password=None)
    log.info("Coinbase ECDSA private key loaded successfully.")
except Exception as e:
    log.exception("Failed to load private key: %s", e)
    raise

# --- Signing function ---
def _sign_request(timestamp: str, method: str, path: str, body: str = "") -> str:
    """
    Returns base64-encoded ECDSA signature for Coinbase Advanced API
    """
    payload = (timestamp + method.upper() + path + (body or "")).encode()
    signature_der = _PRIVATE_KEY.sign(payload, ec.ECDSA(hashes.SHA256()))
    signature_b64 = base64.b64encode(signature_der).decode()
    return signature_b64

# --- Internal request helper ---
def _request(method: str, path: str, body: str = "") -> requests.Response:
    ts = str(int(time.time()))
    signature = _sign_request(ts, method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": ts,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = API_BASE.rstrip("/") + path
    resp = requests.request(method, url, headers=headers, data=body or None, timeout=15)
    log.debug("Request %s %s returned status=%s", method, path, resp.status_code)
    return resp

# --- Public function: fetch USD spot balance ---
def get_usd_spot_balance() -> float:
    """
    Fetch USD spot balance from Coinbase Advanced account.
    Returns float (0.0 if no USD balance)
    """
    resp = _request("GET", "/v2/accounts")
    try:
        data = resp.json()
    except Exception:
        log.error("Failed to decode JSON. Status=%s, body=%s", resp.status_code, resp.text[:2000])
        if resp.status_code == 401:
            raise RuntimeError("Unauthorized: check Coinbase API key/private key")
        resp.raise_for_status()

    for account in data.get("data", []):
        balance = account.get("balance", {})
        if balance.get("currency") == "USD":
            return float(balance.get("amount", 0))
    return 0.0

# --- Public function: fetch all accounts ---
def get_all_accounts() -> list:
    """
    Returns list of all accounts from Coinbase Advanced account
    """
    resp = _request("GET", "/v2/accounts")
    try:
        data = resp.json()
    except Exception:
        log.error("Failed to decode JSON: status=%s, body=%s", resp.status_code, resp.text[:2000])
        resp.raise_for_status()
    return data.get("data", [])

# --- Example usage ---
if __name__ == "__main__":
    try:
        usd_balance = get_usd_spot_balance()
        log.info("✅ USD Spot Balance: %s", usd_balance)
    except Exception as e:
        log.exception("Failed to fetch USD Spot balance: %s", e)
