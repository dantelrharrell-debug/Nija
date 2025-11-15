# ./app/nija_client.py
# Drop this file into your repo at ./app/nija_client.py (overwrite existing).
# Python 3.9+ recommended. Requires: pyjwt, cryptography, requests, loguru

import os
import sys
import time
import datetime
import jwt
import requests
import base64
import json
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------
# Logger setup
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------
# Config / env vars
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")          # UUID like: ce77e4ea-...
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")        # e.g., organizations/{org_id}/apiKeys/{key_id}
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_B64 = os.getenv("COINBASE_PEM_B64")        # optional base64-encoded PEM
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH", "/app/coinbase.pem")
COINBASE_JWT_KID = os.getenv("COINBASE_JWT_KID")        # key id (kid)
COINBASE_SUB = os.getenv("COINBASE_SUB", COINBASE_API_KEY or COINBASE_ORG_ID)  # what to put in 'sub' claim; prefer API_KEY
CB_API_VERSION = os.getenv("CB_API_VERSION", os.getenv("CB_VERSION", "2025-01-01"))
SANDBOX = os.getenv("SANDBOX", "1")                     # set "1" for sandbox, "0" or unset for prod
COINBASE_BASE_URL = os.getenv("COINBASE_BASE_URL")      # override if you want a specific host
TIME_THRESHOLD_SECONDS = int(os.getenv("TIME_THRESHOLD_SECONDS", "60"))  # allowed time skew check

# Default endpoints
SANDBOX_ACCOUNTS = "https://api-public.sandbox.pro.coinbase.com/accounts"
PROD_EXCHANGE_ACCOUNTS = "https://api.exchange.coinbase.com/accounts"
CDP_ACCOUNTS = "https://api.coinbase.com/v2/accounts"  # CDP/advanced trade may use different host; keep here for reference

# -----------------------
# PEM handling utilities
def write_pem_from_env(pem_path=COINBASE_PEM_PATH, min_len=200):
    """Write PEM to disk from COINBASE_PEM_CONTENT (handles literal \\n) or COINBASE_PEM_B64."""
    pem_env = COINBASE_PEM_CONTENT
    b64_env = COINBASE_PEM_B64

    if not pem_env and not b64_env:
        logger.warning("No COINBASE_PEM_CONTENT or COINBASE_PEM_B64 set in environment.")
        return None

    if b64_env:
        try:
            pem_bytes = base64.b64decode(b64_env)
            pem_text = pem_bytes.decode("utf-8")
        except Exception as e:
            logger.exception("Failed to base64-decode COINBASE_PEM_B64: " + str(e))
            return None
    else:
        pem_text = pem_env.replace("\\n", "\n") if ("\\n" in pem_env and "\n" not in pem_env) else pem_env

    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"

    try:
        with open(pem_path, "w", newline="\n") as f:
            f.write(pem_text)
        logger.info(f"Wrote PEM to {pem_path} ({len(pem_text)} bytes)")
        if len(pem_text) < min_len:
            logger.warning(f"PEM looks short ({len(pem_text)} bytes). It may be truncated.")
        return pem_path
    except Exception as e:
        logger.exception("Failed to write PEM to disk: " + str(e))
        return None

def load_private_key(path):
    """Load PEM private key using cryptography. Exits on fatal error."""
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}")
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 50:
            logger.warning(f"PEM file appears small ({len(data)} bytes).")
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded successfully (cryptography key object).")
        return key
    except Exception as e:
        logger.exception("Could not deserialize PEM private key: " + str(e))
        return None

# -----------------------
# JWT build & verify
def build_jwt(private_key, sub_claim, kid=None):
    """Create JWT with ES256. sub_claim should match Coinbase expectation (API key path or org id)."""
    iat = int(time.time())
    payload = {"sub": sub_claim, "iat": iat, "exp": iat + 300}
    headers = {"kid": kid} if kid else {}
    try:
        token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
        # pyjwt returns str in modern versions; if bytes, decode
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token
    except Exception as e:
        logger.exception("Failed to encode JWT: " + str(e))
        return None

def verify_jwt_struct(token):
    """Return decoded header and payload without verifying signature."""
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        return header, payload
    except Exception as e:
        logger.exception("Failed to decode/inspect JWT locally: " + str(e))
        return None, None

# -----------------------
# runtime checks
def check_server_time():
    utcnow = datetime.datetime.utcnow()
    logger.info("Server UTC time: " + utcnow.isoformat())
    # optional - compare to local system time and warn if large skew (we cannot query remote time)
    return utcnow

def choose_accounts_url():
    if COINBASE_BASE_URL:
        # user override
        return COINBASE_BASE_URL.rstrip("/") + "/accounts"
    if SANDBOX and SANDBOX.strip() not in ("0", "false", "False"):
        return SANDBOX_ACCOUNTS
    # prefer exchange endpoints for certain keys; user can override via COINBASE_BASE_URL
    return PROD_EXCHANGE_ACCOUNTS

# -----------------------
# full startup test
def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    logger.info(f"ENV: COINBASE_ORG_ID set: {bool(COINBASE_ORG_ID)} COINBASE_API_KEY set: {bool(COINBASE_API_KEY)} COINBASE_JWT_KID set: {bool(COINBASE_JWT_KID)}")
    logger.info(f"ENV: COINBASE_PEM_CONTENT set: {bool(COINBASE_PEM_CONTENT)} COINBASE_PEM_B64 set: {bool(COINBASE_PEM_B64)} COINBASE_PEM_PATH: {COINBASE_PEM_PATH}")
    check_server_time()

    # ensure we have a pem on disk
    pem_path = COINBASE_PEM_PATH
    if not os.path.exists(pem_path):
        write_pem_from_env(pem_path)

    if not os.path.exists(pem_path):
        logger.error("No PEM file available; cannot continue.")
        return

    key = load_private_key(pem_path)
    if not key:
        logger.error("Private key load failed; check PEM formatting/contents.")
        return

    # Determine sub claim: prefer full API key path if provided
    sub_claim = COINBASE_SUB or COINBASE_API_KEY or COINBASE_ORG_ID
    if not sub_claim:
        logger.error("No sub claim available (set COINBASE_API_KEY or COINBASE_ORG_ID).")
        return

    token = build_jwt(key, sub_claim, COINBASE_JWT_KID)
    if not token:
        logger.error("JWT build failed.")
        return

    logger.info("Generated JWT preview: " + (token[:200] + "..." if len(token) > 200 else token))
    header, payload = verify_jwt_struct(token)
    if header is None:
        logger.error("JWT local inspection failed.")
    else:
        logger.info("JWT header (unverified): " + json.dumps(header))
        logger.info("JWT payload (unverified): " + json.dumps(payload))
        logger.info("JWT header.kid: " + str(header.get("kid")))
        logger.info("JWT payload.sub: " + str(payload.get("sub")))
        # time-skew hint:
        now = int(time.time())
        skew = abs(now - int(payload.get("iat", now)))
        if skew > TIME_THRESHOLD_SECONDS:
            logger.warning(f"Local iat differs from system time by {skew} seconds (threshold {TIME_THRESHOLD_SECONDS}). Clock skew may cause Coinbase to reject token.")

    # Choose test endpoint
    accounts_url = choose_accounts_url()
    logger.info("Testing Coinbase accounts endpoint: " + accounts_url)

    headers_req = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": CB_API_VERSION,
        "User-Agent": "nija-client/1.0"
    }

    try:
        resp = requests.get(accounts_url, headers=headers_req, timeout=15)
        logger.info(f"Coinbase test response status: {resp.status_code}")
        # Do not dump huge bodies; log truncated
        logger.info("Response text (truncated): " + (resp.text[:2000] if resp.text else "<empty>"))
        if resp.status_code == 401:
            logger.error("Received 401 Unauthorized. Things to check: (1) correct 'sub' value, (2) correct 'kid', (3) server clock skew, (4) key permissions or revoked key, (5) using the endpoint matching the key type (sandbox vs prod).")
    except Exception as e:
        logger.exception("HTTP request to Coinbase failed: " + str(e))

# -----------------------
# Exposed helper: get headers for use by the rest of app
def get_coinbase_headers():
    # ensures PEM exists and loads key each time (simple approach)
    if not os.path.exists(COINBASE_PEM_PATH):
        write_pem_from_env(COINBASE_PEM_PATH)
    key = load_private_key(COINBASE_PEM_PATH)
    if not key:
        raise RuntimeError("Could not load private key.")
    sub_claim = COINBASE_SUB or COINBASE_API_KEY or COINBASE_ORG_ID
    token = build_jwt(key, sub_claim, COINBASE_JWT_KID)
    return {"Authorization": f"Bearer {token}", "CB-VERSION": CB_API_VERSION}

# -----------------------
# Run test on direct invocation
if __name__ == "__main__":
    startup_test()
