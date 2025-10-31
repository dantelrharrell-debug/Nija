import os
import jwt
import time
import base64
import logging

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_KEY_B64 = os.getenv("COINBASE_PEM_KEY_B64")

def get_jwt_token() -> str:
    if not COINBASE_PEM_KEY_B64 or not COINBASE_API_KEY_ID or not COINBASE_ORG_ID:
        raise ValueError("Missing Coinbase JWT environment variables")

    pem_bytes = base64.b64decode(COINBASE_PEM_KEY_B64)
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 minutes expiry
        "sub": COINBASE_ORG_ID,
        "jti": COINBASE_API_KEY_ID
    }
    token = jwt.encode(payload, pem_bytes, algorithm="ES256")
    logger.info("[NIJA-JWT] JWT generated successfully")
    return token
