import os
import time
import jwt  # PyJWT
import logging
import base64
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

# Environment variables
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID", "").strip()
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID", "").strip()
COINBASE_PEM_KEY_B64 = os.getenv("COINBASE_PEM_KEY_B64", "").strip()

# Decode base64 PEM
def _load_pem():
    try:
        pem_bytes = base64.b64decode(COINBASE_PEM_KEY_B64)
        key = serialization.load_pem_private_key(pem_bytes, password=None)
        return key
    except Exception as e:
        logger.error("[NIJA-JWT] Failed to load PEM key: %s", e)
        raise

def get_jwt_token() -> str:
    if not (COINBASE_API_KEY_ID and COINBASE_ORG_ID and COINBASE_PEM_KEY_B64):
        raise ValueError("[NIJA-JWT] Missing JWT environment variables.")

    private_key = _load_pem()
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 min expiry
        "jti": str(now),
        "iss": COINBASE_ORG_ID,
        "sub": COINBASE_API_KEY_ID,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    logger.info("[NIJA-JWT] JWT token preview (first 20 chars): %s", str(token)[:20])
    return token
