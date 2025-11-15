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
# Config / Paths
# -----------------------------
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 200  # Coinbase PEMs are usually >200 bytes

# -----------------------------
# Write PEM from environment
# -----------------------------
def write_pem_from_env():
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_env:
        logger.error("COINBASE_PEM_CONTENT not set in environment.")
        sys.exit(1)

    pem_text = pem_env.replace("\\n", "\n") if "\\n" in pem_env and "\n" not in pem_env else pem_env
    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"

    if len(pem_text) < MIN_PEM_LENGTH:
        logger.warning(f"PEM looks very short ({len(pem_text)} bytes).")

    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(pem_text)
        logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(pem_text)} bytes)")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception(f"Failed to write PEM file: {e}")
        sys.exit(1)

# -----------------------------
# Load Private Key
# -----------------------------
def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}.")
        sys.exit(1)

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < MIN_PEM_LENGTH:
        logger.error(f"PEM file too short ({len(data)} bytes).")
        sys.exit(1)

    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded successfully.")
        return key
    except Exception as e:
        logger.exception(f"Failed to deserialize PEM private key: {e}")
        sys.exit(1)

# -----------------------------
# Build JWT
# -----------------------------
def build_jwt(private_key, org_id, kid):
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}  # 5 min expiry
    headers = {"kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# -----------------------------
# Test Coinbase API
# -----------------------------
def test_coinbase(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("CB_API_VERSION", datetime.date.today().isoformat())
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
    logger.info("=== Nija Coinbase JWT Startup Test ===")

    # PEM
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    key = load_private_key(pem_path)

    # Organization ID and Key ID
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")
    if not org_id or not kid:
        logger.error("Missing COINBASE_ORG_ID or COINBASE_JWT_KID")
        sys.exit(1)

    # Build JWT
    token = build_jwt(key, org_id, kid)
    logger.info("JWT generated (preview): " + token[:200])

    # Decode unverified JWT for debug
    try:
        hdr = jwt.get_unverified_header(token)
        pl = jwt.decode(token, options={"verify_signature": False})
        logger.info(f"JWT header: {hdr}")
        logger.info(f"JWT payload: {pl}")
    except Exception as e:
        logger.warning(f"Failed to decode JWT locally: {e}")

    # Test Coinbase
    resp = test_coinbase(token)
    if resp is None:
        logger.error("No response from Coinbase.")
    else:
        logger.info(f"Coinbase status code: {resp.status_code}")
        logger.info("Coinbase response (truncated 2000 chars):\n" + (resp.text[:2000] if resp.text else ""))

# -----------------------------
# Get headers for API calls
# -----------------------------
def get_coinbase_headers():
    pem_path = os.environ.get("COINBASE_PEM_PATH") or PEM_FILE_PATH
    key = load_private_key(pem_path)
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")
    token = build_jwt(key, org_id, kid)
    return {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("CB_API_VERSION", datetime.date.today().isoformat())
    }

# -----------------------------
# Run test if standalone
# -----------------------------
if __name__ == "__main__":
    startup_test()
