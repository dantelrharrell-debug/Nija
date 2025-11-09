#!/usr/bin/env python3
"""
nija_advanced_client.py
Generate a REST JWT for Coinbase Advanced (service key), call /api/v3/brokerage/accounts,
and return parsed accounts with robust error handling (no crashes).
"""

import os
import time
import logging
import requests

# Use the official helper from coinbase-advanced-py
# pip install coinbase-advanced-py
try:
    from coinbase import jwt_generator
except Exception:
    jwt_generator = None

LOG = logging.getLogger("nija.coinbase.advanced")
logging.basicConfig(level=logging.INFO)

API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")  # Coinbase Advanced base
API_ACCOUNTS_PATH = "/api/v3/brokerage/accounts"

# env vars you must set (examples)
# COINBASE_ISS -> organizations/{org_id}/apiKeys/{key_id}   (the API key id string)
# COINBASE_PEM_CONTENT -> the PEM private key text (-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n)
# OR set COINBASE_PRIVATE_KEY_PATH to a path (if you pre-upload file)
KEY_ID = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_API_KEY")  # keep compatibility
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
PEM_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH", "/tmp/coinbase_key.pem")

def ensure_pem_file():
    # If user provided PEM content in an env var, write it to a secure temp file.
    if PEM_CONTENT and not os.path.exists(PEM_PATH):
        LOG.info("Writing PEM from COINBASE_PEM_CONTENT to %s", PEM_PATH)
        with open(PEM_PATH, "w", encoding="utf-8") as f:
            f.write(PEM_CONTENT)
        os.chmod(PEM_PATH, 0o600)
    if not os.path.exists(PEM_PATH):
        LOG.warning("No PEM file found at %s and COINBASE_PEM_CONTENT not set.", PEM_PATH)
        return False
    return True

def build_jwt_for_request(method: str, path: str) -> str:
    """
    Build a JWT for a single REST call using the helper from coinbase-advanced-py.
    The helper expects a 'formatted' URI like: "GET api.coinbase.com/api/v3/brokerage/accounts"
    """
    if jwt_generator is None:
        raise RuntimeError("coinbase.jwt_generator not available. Install coinbase-advanced-py.")

    if not KEY_ID:
        raise RuntimeError("COINBASE_ISS (organizations/.../apiKeys/...) not set")

    uri = jwt_generator.format_jwt_uri(method, path)  # builds "GET api.coinbase.com/api/v3/..."
    # KEY_ID is the 'key' string (organizations/.../apiKeys/...)
    # PEM_CONTENT or PEM_PATH is the private key (ES256)
    pem = PEM_PATH if os.path.exists(PEM_PATH) else PEM_CONTENT
    token = jwt_generator.build_rest_jwt(uri, KEY_ID, pem)
    return token

def fetch_accounts():
    """
    Return (status_code, dict_or_text). Handles 401/404 and non-JSON responses without crashing.
    """
    if not ensure_pem_file():
        return 0, "Missing PEM for JWT generation (set COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH)"

    try:
        jwt = build_jwt_for_request("GET", API_ACCOUNTS_PATH)
    except Exception as e:
        LOG.exception("Failed to build JWT: %s", e)
        return 0, f"JWT error: {e}"

    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
        "CB-VERSION": "2025-11-09"  # not required but OK
    }
    url = API_BASE.rstrip("/") + API_ACCOUNTS_PATH

    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except Exception as e:
        LOG.exception("HTTP request failed: %s", e)
        return 0, f"request error: {e}"

    # handle non-JSON gracefully
    body = resp.text[:2000] if resp.text else ""
    if resp.status_code >= 400:
        LOG.warning("Status: %s, Body: %s", resp.status_code, body)
        return resp.status_code, body

    try:
        data = resp.json()
    except ValueError:
        LOG.warning("JSON decode failed; returning raw body. (%s)", body[:2000])
        return resp.status_code, body

    return resp.status_code, data

if __name__ == "__main__":
    status, accounts = fetch_accounts()
    if status == 200:
        LOG.info("✅ Accounts fetched successfully.")
        # accounts likely contains { "data": [ ... ] }
        acct_list = accounts.get("data") if isinstance(accounts, dict) else None
        if acct_list:
            for a in acct_list:
                name = a.get("name") or a.get("id")
                cur = a.get("currency") or a.get("currency_code") or "?"
                bal = a.get("balance", {}).get("amount") if isinstance(a.get("balance"), dict) else a.get("balance")
                LOG.info(" - %s (%s): %s", name, cur, bal)
        else:
            LOG.info("Response body (no 'data' key): %s", accounts)
    else:
        LOG.error("❌ Failed to fetch accounts. Status: %s, Response: %s", status, accounts)
