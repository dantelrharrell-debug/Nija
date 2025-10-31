import os
import jwt  # pip install pyjwt[crypto]
import time
import logging

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_KEY = os.getenv("COINBASE_PEM_KEY")  # full PEM, multi-line string

def get_jwt_token() -> str:
    """
    Generate JWT for Coinbase Advanced API
    """
    if not (COINBASE_API_KEY_ID and COINBASE_ORG_ID and COINBASE_PEM_KEY):
        raise ValueError("Missing required Coinbase JWT environment variables.")

    # JWT payload
    payload = {
        "sub": COINBASE_API_KEY_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 minutes
        "org_id": COINBASE_ORG_ID
    }

    try:
        token = jwt.encode(
            payload,
            COINBASE_PEM_KEY,
            algorithm="ES256"
        )
        return token
    except Exception as e:
        logger.error("[NIJA-JWT] Failed to generate JWT: %s", e)
        raise

def debug_print_jwt_payload():
    token = get_jwt_token()
    logger.info("[NIJA-JWT] JWT token preview (first 20 chars): %s", token[:20])
