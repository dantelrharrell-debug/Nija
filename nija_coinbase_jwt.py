import os
import logging
import time
import jwt  # PyJWT

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID", "").strip()
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID", "").strip()
COINBASE_PEM_KEY = os.getenv("COINBASE_PEM_KEY", "").strip()

def get_jwt_token() -> str:
    if not COINBASE_API_KEY_ID or not COINBASE_ORG_ID or not COINBASE_PEM_KEY:
        raise ValueError("Missing JWT env variables")

    payload = {
        "sub": COINBASE_API_KEY_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "org_id": COINBASE_ORG_ID,
    }

    token = jwt.encode(payload, COINBASE_PEM_KEY, algorithm="ES256")
    return token
