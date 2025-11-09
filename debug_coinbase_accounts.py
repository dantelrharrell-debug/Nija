#!/usr/bin/env python3
"""
debug_coinbase_accounts.py

Try many combos (Advanced JWT vs Retail HMAC) and many base URLs/endpoints,
log everything safely (no JSON exceptions), and report which combo works.
Put this in your repo root and run: python3 debug_coinbase_accounts.py
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# load .env during local testing
load_dotenv()

# Config
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

# Possible base URLs to try (common ones seen in your logs)
BASE_URLS = [
    os.getenv("COINBASE_API_BASE"),               # if user explicitly set it
    "https://api.coinbase.com",
    "https://api.cdp.coinbase.com",
    "https://api.exchange.coinbase.com",         # retail exchange base (sometimes used)
]
BASE_URLS = [b for b in BASE_URLS if b]  # drop Nones

# Endpoints to try (Advanced v3, generic v3/v2, retail)
ENDPOINTS = [
    "/api/v3/brokerage/accounts",  # Advanced brokerage accounts (Common Advanced endpoint)
    "/v3/accounts",
    "/v2/accounts",
    "/accounts",
    "/api/v3/accounts",
]

# Env-based credentials
KEY_ID = os.getenv("COINBASE_KEY_ID")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
PEM_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH")
HMAC_KEY = os.getenv("COINBASE_API_KEY")
HMAC_SECRET = os.getenv("COINBASE_API_SECRET")
HMAC_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# helpers
def read_pem_from_path(p):
    try:
        return Path(p).read_text()
    except Exception as e:
        logger.exception(f"Can't read PEM at {p}: {e}")
        return None

if not PEM_CONTENT and PEM_PATH:
    PEM_CONTENT = read_pem_from_path(PEM_PATH)

# JWT helper (try import if coinbase-advanced-py installed)
HAS_JWT_HELPER = False
try:
    from coinbase import jwt_generator
    HAS_JWT_HELPER = True
except Exception:
    HAS_JWT_HELPER = False

def build_jwt(method, path):
    """Build a REST JWT using coinbase-advanced-py if available, else return None."""
    if not HAS_JWT_HELPER:
        logger.debug("JWT helper not installed (coinbase-advanced-py). Skipping JWT build.")
        return None
    try:
        uri = jwt_generator.format_jwt_uri(method.upper(), path)
        token = jwt_generator.build_rest_jwt(uri, KEY_ID, PEM_CONTENT)
        return token
    except Exception as e:
        logger.exception(f"JWT build failed: {e}")
        return None

def safe_json(resp):
    """Return (is_json_bool, parsed_or_text) safely"""
    text = resp.text if hasattr(resp, "text") else str(resp)
    try:
        return True, resp.json()
    except Exception:
        return False, text

def jwt_request(base, method, path):
    token = build_jwt(method, path)
    if not token:
        return None, "no_jwt"
    url = base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        return None, f"request_err: {e}"
    is_json, body = safe_json(resp)
    return resp.status_code, (body if is_json else body)

def hmac_request(base, method, path, body=None):
    """Simple retail HMAC style (CB-ACCESS-SIGN) — best-effort; there are flavors."""
    if not (HMAC_KEY and HMAC_SECRET):
        return None, "no_hmac_creds"
    url = base.rstrip("/") + path
    ts = str(int(time.time()))
    payload = body or ""
    message = ts + method.upper() + path + (json.dumps(body) if body else "")
    # Many retail HMACs use base64 of hmac.sha256 digest and sometimes hex; try base64 first (common)
    try:
        sig_b64 = base64.b64encode(hmac.new(HMAC_SECRET.encode(), message.encode(), hashlib.sha256).digest()).decode()
        sig_hex = hmac.new(HMAC_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    except Exception as e:
        return None, f"hmac_err: {e}"

    headers = {
        "CB-ACCESS-KEY": HMAC_KEY,
        "CB-ACCESS-TIMESTAMP": ts,
        # We'll try both sign flavors via header override later if needed
        "Content-Type": "application/json",
    }
    # try base64 signature first as CB-ACCESS-SIGN sometimes expects base64
    headers["CB-ACCESS-SIGN"] = sig_b64
    if HMAC_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = HMAC_PASSPHRASE

    try:
        resp = requests.request(method, url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        return None, f"request_err: {e}"

    is_json, body = safe_json(resp)
    return resp.status_code, (body if is_json else body)

def try_all():
    results = []
    for base in BASE_URLS:
        logger.info(f"Trying base URL: {base}")
        for path in ENDPOINTS:
            # Try Advanced JWT if creds present
            if KEY_ID and (PEM_CONTENT or PEM_PATH) and HAS_JWT_HELPER:
                status, body = jwt_request(base, "GET", path)
                results.append(("JWT", base, path, status, body))
                logger.info(f"[JWT] {base}{path} -> status={status} body_type={'json' if isinstance(body, (dict,list)) else 'text'}")
                if status == 200:
                    return "JWT", base, path, status, body

            # Try HMAC retail if creds present
            if HMAC_KEY and HMAC_SECRET:
                status, body = hmac_request(base, "GET", path)
                results.append(("HMAC", base, path, status, body))
                logger.info(f"[HMAC] {base}{path} -> status={status} body_type={'json' if isinstance(body, (dict,list)) else 'text'}")
                if status == 200:
                    return "HMAC", base, path, status, body

    return None, results

def pretty_report(out):
    if out is None:
        logger.error("No working combo found. See detailed logs above.")
        return
    auth_type, base, path, status, body = out
    logger.success(f"Working combo found: auth={auth_type} base={base} path={path} status={status}")
    if isinstance(body, (dict, list)):
        logger.info("Response JSON (trimmed):")
        try:
            logger.info(json.dumps(body, indent=2)[:3000])
        except Exception:
            logger.info(str(body)[:3000])
    else:
        logger.info("Response text (trimmed):")
        logger.info(str(body)[:2000])

if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), colorize=True)

    logger.info("Starting coinbase account debug probe.")
    if not BASE_URLS:
        logger.error("No BASE_URLS configured. Set COINBASE_API_BASE or leave defaults.")
        raise SystemExit(1)

    # First attempt: try all combos once
    out = try_all()
    if isinstance(out, tuple) and out[0] in ("JWT", "HMAC"):
        pretty_report(out)
        raise SystemExit(0)

    # If nothing worked, print aggregated results (out contains list of attempts)
    logger.warning("No 200 OK responses found. Full attempt log printed above.")
    logger.info("Tips: check COINBASE_KEY_ID format, PEM presence, HMAC key type, and key permissions (accounts.read).")
    raise SystemExit(2)
