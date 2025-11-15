# app/nija_client.py
import os
import sys
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Logging
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# Env / Paths
# -----------------------------
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 200

COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_JWT_KID = os.environ.get("COINBASE_JWT_KID")  # Must match UUID of API Key

if not all([COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_JWT_KID]):
    logger.error("Missing required env vars: COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_JWT_KID")
    sys.exit(1)

# -----------------------------
# PEM Handling
# -----------------------------
def write_pem_from_env():
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_env:
        logger.error("COINBASE_PEM_CONTENT not set")
        sys.exit(1)
    # convert literal \n into real newlines if necessary
    pem_text = pem_env.replace("\\n", "\n") if "\\n" in pem_env else pem_env
    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"

    if len(pem_text) < MIN_PEM_LENGTH:
        logger.warning(f"COINBASE_PEM_CONTENT looks very short ({len(pem_text)} bytes)")

    with open(PEM_FILE_PATH, "w", newline="\n") as f:
        f.write(pem_text)
    logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(pem_text)} bytes)")
    return PEM_FILE_PATH

def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}")
        sys.exit(1)

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < MIN_PEM_LENGTH:
        logger.error(f"PEM file too short ({len(data)} bytes)")
        sys.exit(1)

    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info(f"Private key loaded successfully. Key type: {type(key)}")
        return key
    except Exception as e:
        logger.exception(f"Failed to deserialize PEM: {e}")
        sys.exit(1)

# -----------------------------
# JWT Generation
# -----------------------------
def build_jwt(private_key, org_id, kid):
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}  # 5 min expiry
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# -----------------------------
# Coinbase Test Call
# -----------------------------
def test_coinbase(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")
    }
    try:
        resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers, timeout=12)
        return resp
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")
        return None

# -----------------------------
# Startup Test
# -----------------------------
def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = PEM_FILE_PATH if os.path.exists(PEM_FILE_PATH) else write_pem_from_env()
    key = load_private_key(pem_path)
    token = build_jwt(key, COINBASE_ORG_ID, COINBASE_JWT_KID)
    logger.info(f"Generated JWT (preview): {token[:50]}...")

    # Decode locally for verification
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info(f"JWT header: {header}")
        logger.info(f"JWT payload: {payload}")
    except Exception as e:
        logger.warning(f"Failed local JWT decode: {e}")

    # Coinbase API call
    resp = test_coinbase(token)
    if resp is None:
        logger.error("No response from Coinbase")
        return
    logger.info(f"Coinbase response: {resp.status_code}")
    if resp.status_code != 200:
        logger.error(f"Unauthorized or error: {resp.text[:500]}")

# -----------------------------
# Helper to get headers for API calls
# -----------------------------
def get_coinbase_headers():
    pem_path = PEM_FILE_PATH
    key = load_private_key(pem_path)
    token = build_jwt(key, COINBASE_ORG_ID, COINBASE_JWT_KID)
    return {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")
    }

# -----------------------------
# Run test if called directly
# -----------------------------
if __name__ == "__main__":
    startup_test()
