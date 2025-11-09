#!/usr/bin/env python3
"""
Start file: start_nija_live_hmac.py
Put at project root (/app/start_nija_live_hmac.py) and make sure your Railway/Procfile starts this file.
This script is defensive: it tries Advanced (CDP) endpoints first when Advanced=True,
then falls back to retail HMAC endpoints. It will NOT crash on JSON decode errors and
logs full response bodies for debugging.
"""

import os
import time
import logging
import requests
from loguru import logger

# optional import of your local HMAC client (if present)
try:
    from nija_hmac_client import CoinbaseClient as NijaHMACClient
except Exception:
    NijaHMACClient = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.hmac.start")

# Config from env
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "").rstrip("/")
COINBASE_PRIVATE_KEY_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH") or os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ISS = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ISSUER")
ADVANCED_MODE = os.getenv("COINBASE_ADVANCED", "") in ("1", "true", "True") or bool(COINBASE_PRIVATE_KEY_PATH or COINBASE_ISS)

# Candidate endpoints (host + path) to try for accounts:
ADVANCED_ENDPOINTS = [
    # Common Advanced (CDP) production patterns
    (COINBASE_API_BASE or "https://api.cdp.coinbase.com", "/api/v3/brokerage/accounts"),
    (COINBASE_API_BASE or "https://api.cdp.coinbase.com", "/api/v3/accounts"),
    # older/alternate host patterns (if your COINBASE_API_BASE set to api.coinbase.com)
    ("https://api.coinbase.com", "/api/v3/brokerage/accounts"),
    ("https://api.coinbase.com", "/api/v3/accounts"),
]

RETAIL_ENDPOINTS = [
    (COINBASE_API_BASE or "https://api.coinbase.com", "/v2/accounts"),
    ("https://api.coinbase.com", "/v2/accounts"),
    ("https://api.coinbase.com", "/accounts"),
]

HEADERS_BASE = {
    "Content-Type": "application/json",
}

def try_request_simple(method, base, path, headers=None, timeout=10):
    url = base.rstrip("/") + path
    headers = headers or {}
    logger.info(f"DEBUG -> trying {method} {url}")
    try:
        resp = requests.request(method, url, headers=headers, timeout=timeout)
    except Exception as e:
        logger.exception(f"Request error for {url}: {e}")
        return resp_status_text_tuple(None, None, str(e))

    status = resp.status_code
    text = resp.text
    logger.debug(f"Response status={status}, body={text[:1000]!r}")
    # try parse JSON safely
    try:
        data = resp.json()
        return status, data, text
    except Exception as e:
        # not JSON: return raw text as data=None, but include body for debugging
        logger.warning(f"⚠️ JSON decode failed. Status: {status}, Body: {text[:1000]!r}")
        return status, None, text

def resp_status_text_tuple(status, data, text):
    return status, data, text

def fetch_accounts_via_client():
    """Use your nija_hmac_client if available; keep it defensive (no crash)."""
    if NijaHMACClient is None:
        logger.info("Local nija_hmac_client not available; skipping client-based fetch.")
        return None, None
    try:
        client = NijaHMACClient()
        # many client implementations have 'request' or 'get_accounts' - try both
        if hasattr(client, "request"):
            status, data = client.request(method="GET", path="/v2/accounts")
            return status, data
        if hasattr(client, "get_accounts"):
            status, data = client.get_accounts()
            return status, data
        logger.info("nija_hmac_client exists but has no 'request' or 'get_accounts' API.")
        return None, None
    except Exception as e:
        logger.exception("Exception while using nija_hmac_client")
        return None, None

def fetch_accounts():
    # 1) If Advanced mode, try the Advanced endpoints first using simple requests.
    if ADVANCED_MODE:
        logger.info("Using Coinbase Advanced (CDP) mode detection. Trying v3 (brokerage) endpoints.")
        for base, path in ADVANCED_ENDPOINTS:
            status, data, body = try_request_simple("GET", base, path, headers=HEADERS_BASE)
            # if JSON and accounts present, return
            if status == 200 and data:
                logger.info(f"✅ Advanced accounts fetched from {base}{path}")
                return status, data
            # if 401/403/404 keep trying, but log
            logger.warning(f"Attempt on {base}{path} returned {status}. Body start: {repr(body)[:200]}")
        logger.warning("Advanced mode: tried common v3 endpoints and none returned accounts.")
        # fall through to retail try if desired
    else:
        logger.info("Not in Advanced mode. Trying retail endpoints (HMAC v2).")

    # 2) Try local client-based fetch (if exists) — sometimes client knows how to sign
    status, data = fetch_accounts_via_client()
    if status:
        if status == 200 and data:
            logger.info("✅ Accounts fetched via local nija_hmac_client")
            return status, data
        logger.warning(f"Local client returned status {status}. Data: {type(data)}")

    # 3) Try retail endpoints (v2)
    logger.info("Trying Retail HMAC endpoints (v2) as fallback.")
    for base, path in RETAIL_ENDPOINTS:
        status, data, body = try_request_simple("GET", base, path, headers=HEADERS_BASE)
        if status == 200 and data:
            logger.info(f"✅ Retail accounts fetched from {base}{path}")
            return status, data
        logger.warning(f"Attempt on {base}{path} returned {status}. Body start: {repr(body)[:200]}")

    # Nothing worked
    logger.error("❌ No accounts found after trying Advanced + local client + retail endpoints.")
    return None, None

def main():
    logger.info("Starting HMAC/Advanced account fetch verification...")
    status, accounts = fetch_accounts()
    if not status or status != 200 or not accounts:
        logger.error("No HMAC accounts found. Bot will not start. Check the following:")
        logger.error(" - COINBASE_API_BASE (should be correct for your key type)")
        logger.error(" - If using Advanced (CDP) you MUST generate a JWT signed with your private key/PEM and request /api/v3/brokerage/accounts (or use the official SDK).")
        logger.error(" - If using Retail HMAC, check key permissions include accounts read and the signing flavor is CB-ACCESS-SIGN on https://api.coinbase.com/v2/accounts")
        logger.info("Exiting safely (no crash).")
        return

    # If we reached here we have accounts dict (or list)
    try:
        # If accounts is a dict with 'data' key (Coinbase typical), use that
        data_list = accounts.get("data") if isinstance(accounts, dict) and "data" in accounts else accounts
        logger.info("✅ Accounts fetched successfully. Listing:")
        for acct in data_list:
            name = acct.get("name") if isinstance(acct, dict) else str(acct)
            currency = acct.get("currency") if isinstance(acct, dict) else ""
            bal = acct.get("balance", {}).get("amount") if isinstance(acct, dict) else ""
            logger.info(f" - {name} ({currency}): {bal}")
    except Exception:
        logger.exception("Error while logging accounts")

    # At this point you could continue to start your trading loop safely (not done here).
    logger.info("HMAC/Advanced verification complete. If accounts looked good you can proceed to start trading loop.")

if __name__ == "__main__":
    main()
