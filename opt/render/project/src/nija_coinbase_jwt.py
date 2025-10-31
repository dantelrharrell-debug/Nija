import os
import jwt
import time
import logging

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_KEY_B64 = os.getenv("COINBASE_PEM_KEY_B64")

def get_jwt_token():
    if not (COINBASE_API_KEY_ID and COINBASE_ORG_ID and COINBASE_PEM_KEY_B64):
        raise ValueError("Missing required Coinbase JWT environment variables")

    # Decode base64 PEM
    pem_bytes = COINBASE_PEM_KEY_B64.encode()
    payload = {
        "sub": COINBASE_API_KEY_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "iss": COINBASE_ORG_ID,
    }
    token = jwt.encode(payload, pem_bytes, algorithm="ES256")
    return token
