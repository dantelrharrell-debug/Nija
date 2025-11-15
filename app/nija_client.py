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
# Logging setup
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# PEM & JWT helpers
# -----------------------------
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 200  # Coinbase PEMs are usually >200 bytes

def write_pem_from_env():
    """Write PEM from COINBASE_PEM_CONTENT to PEM_FILE_PATH"""
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_env:
        logger.warning("COINBASE_PEM_CONTENT not set. Skipping PEM write.")
        return None
    pem_text = pem_env.replace("\\n", "\n") if "\\n" in pem_env and "\n" not in pem_env else pem_env
    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"
    if len(pem_text) < MIN_PEM_LENGTH:
        logger.warning(f"COINBASE_PEM_CONTENT looks short ({len(pem_text)} bytes).")
    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(pem_text)
        logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(pem_text)} bytes)")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception(f"Failed to write PEM file: {e}")
        return None

def load_private_key(path):
    """Load PEM private key from file"""
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
        logger.info("Private key loaded successfully.")
        return key
    except Exception as e:
        logger.exception(f"Failed to deserialize PEM private key: {e}")
        sys.exit(1)

def build_jwt(private_key, org_id, kid=None):
    """Generate Coinbase JWT"""
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}  # 5 min expiry
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# -----------------------------
# Startup test
# -----------------------------
def startup_test():
    """Full startup test: write/load PEM, generate JWT, call Coinbase Advanced Trade API"""
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")  # API Key ID

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH, ORG_ID, or KID; cannot proceed with JWT generation.")
        return

    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    logger.info("Generated JWT (preview): " + (token[:200] if token else ""))

    # ✅ Test Coinbase Advanced Trade API
    try:
        resp = requests.get(
            "https://api.exchange.coinbase.com/accounts",
            headers={"Authorization": f"Bearer {token}"}, timeout=12
        )
        logger.info("Status code: " + str(resp.status_code))
        logger.info("Response (truncated 2000 chars):\n" + (resp.text[:2000] if resp.text else ""))
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")

# -----------------------------
# Main entry
# -----------------------------
if __name__ == "__main__":
    startup_test()
