# app/nija_client.py
import os
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Setup logger
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# Configuration
# -----------------------------
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
KID = os.environ.get("COINBASE_JWT_KID")
CB_API_VERSION = os.environ.get("CB_API_VERSION", "2025-01-01")

# -----------------------------
# Load private key from PEM
# -----------------------------
def load_private_key(path):
    try:
        with open(path, "rb") as f:
            key_data = f.read()
        private_key = serialization.load_pem_private_key(
            key_data, password=None, backend=default_backend()
        )
        logger.info("Private key loaded successfully.")
        return private_key
    except Exception as e:
        logger.exception(f"Failed to load private key from {path}: {e}")
        raise

# -----------------------------
# Build JWT
# -----------------------------
def build_jwt(private_key, org_id, kid=None):
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# -----------------------------
# Test Coinbase API
# -----------------------------
def test_coinbase(token):
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": CB_API_VERSION}
    try:
        resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers, timeout=12)
        return resp
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")
        return None

# -----------------------------
# Startup test
# -----------------------------
def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    logger.info(f"PEM_PATH: {PEM_FILE_PATH}")
    logger.info(f"ORG_ID : {ORG_ID}")
    logger.info(f"KID    : {KID}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not PEM_FILE_PATH or not ORG_ID:
        logger.error("Missing PEM_PATH or ORG_ID; cannot generate JWT.")
        return

    try:
        private_key = load_private_key(PEM_FILE_PATH)
    except Exception:
        logger.error("Private key load failed; cannot continue.")
        return

    token = build_jwt(private_key, ORG_ID, KID)
    logger.info("Generated JWT (preview): " + token[:200])

    # Optional: decode locally for debugging
    try:
        unverified_header = jwt.get_unverified_header(token)
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        logger.info(f"JWT header (unverified): {unverified_header}")
        logger.info(f"JWT payload (unverified): {unverified_payload}")
    except Exception as e:
        logger.warning(f"Failed to decode JWT locally: {e}")

    resp = test_coinbase(token)
    if resp is None:
        logger.error("No response from Coinbase.")
        return
    logger.info(f"Coinbase test response: {resp.status_code}")
    logger.info("Coinbase response (truncated 2000 chars):\n" + (resp.text[:2000] if resp.text else ""))

# Run startup test on import
startup_test()

# -----------------------------
# Helper to generate headers for requests
# -----------------------------
def get_coinbase_headers():
    key = load_private_key(PEM_FILE_PATH)
    token = build_jwt(key, ORG_ID, KID)
    return {"Authorization": f"Bearer {token}", "CB-VERSION": CB_API_VERSION}
