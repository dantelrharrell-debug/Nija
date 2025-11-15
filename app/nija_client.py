import os
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.add(lambda msg: print(msg, end=''))  # basic console logging

# -------------------------------
# Load/write PEM
# -------------------------------
def write_pem_from_env():
    pem_content = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_content:
        raise ValueError("COINBASE_PEM_CONTENT not set")
    pem_path = "/app/coinbase.pem"
    with open(pem_path, "w", newline="\n") as f:
        f.write(pem_content.replace("\\n", "\n"))
    logger.info(f"PEM written to {pem_path}")
    return pem_path

def load_private_key(pem_path):
    with open(pem_path, "rb") as f:
        key_data = f.read()
    key = serialization.load_pem_private_key(key_data, password=None, backend=default_backend())
    logger.info("✅ PEM loaded successfully. Key type: " + str(type(key)))
    return key

# -------------------------------
# Build JWT
# -------------------------------
def build_jwt(key, org_id, kid):
    now = int(time.time())
    payload = {
        "sub": org_id,
        "iat": now,
        "exp": now + 300  # max 5 minutes
    }
    headers = {"kid": kid}
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

# -------------------------------
# Verify JWT structure locally
# -------------------------------
def verify_jwt(token):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info("✅ JWT structure is valid")
        logger.info("JWT header: " + str(header))
        logger.info("JWT payload: " + str(payload))
        print("Header:", header)
        print("Payload:", payload)
    except Exception as e:
        logger.exception("❌ JWT verification failed: " + str(e))
        return False
    return True

# -------------------------------
# Full startup test
# -------------------------------
def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")  # API Key ID (UUID only!)

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH, ORG_ID, or KID; cannot proceed with JWT generation.")
        return

    # Load private key
    key = load_private_key(pem_path)

    # Build JWT
    token = build_jwt(key, org_id, kid)
    logger.info("Generated JWT (preview): " + token[:200])

    # Verify JWT locally
    if not verify_jwt(token):
        logger.error("JWT is invalid. Stop before sending request.")
        return

    # Test Coinbase Advanced Trade API
    try:
        resp = requests.get(
            "https://api.exchange.coinbase.com/accounts",
            headers={"Authorization": f"Bearer {token}"},
            timeout=12
        )
        logger.info("Status code: " + str(resp.status_code))
        logger.info("Response body (truncated): " + resp.text[:2000])
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")

# -------------------------------
# Run test
# -------------------------------
if __name__ == "__main__":
    startup_test()
