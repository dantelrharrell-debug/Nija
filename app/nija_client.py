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
# Logging setup
# -----------------------------
logger.add("nija.log", rotation="5 MB")

# -----------------------------
# Helpers
# -----------------------------
def write_pem_from_env():
    pem_content = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_content:
        logger.error("COINBASE_PEM_CONTENT not set!")
        return None
    pem_path = "/app/coinbase.pem"
    with open(pem_path, "w", newline="\n") as f:
        f.write(pem_content.replace("\\n", "\n"))
    logger.info(f"PEM written to {pem_path}")
    return pem_path

def load_private_key(pem_path):
    with open(pem_path, "rb") as f:
        key_data = f.read()
    key = serialization.load_pem_private_key(
        key_data, password=None, backend=default_backend()
    )
    logger.info(f"PEM loaded successfully. Key type: {type(key)}")
    return key

def build_jwt(key, org_id, kid):
    now = int(time.time())
    payload = {
        "sub": org_id,
        "iat": now,
        "exp": now + 300  # 5 min expiry
    }
    headers = {"kid": kid}
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

# -----------------------------
# Startup Test
# -----------------------------
def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")

    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH, ORG_ID, or KID; cannot proceed with JWT generation.")
        return

    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    logger.info("Generated JWT (preview): " + token[:200])

    # ✅ Test Coinbase Advanced Trade API
    try:
        resp = requests.get(
            "https://api.exchange.coinbase.com/accounts",
            headers={"Authorization": f"Bearer {token}"},
            timeout=12
        )
        logger.info("Status code: " + str(resp.status_code))
        logger.info("Response (truncated): " + resp.text[:2000])
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")

# -----------------------------
# Run test on script start
# -----------------------------
if __name__ == "__main__":
    startup_test()
