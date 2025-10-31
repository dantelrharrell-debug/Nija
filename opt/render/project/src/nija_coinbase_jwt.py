import os
import jwt
import time
import logging
import base64

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

def get_jwt_token() -> str:
    """
    Generate a JWT token from PEM key.
    Requires COINBASE_API_KEY_ID, COINBASE_ORG_ID, and COINBASE_PEM_KEY_B64.
    """
    key_id = os.getenv("COINBASE_API_KEY_ID", "").strip()
    org_id = os.getenv("COINBASE_ORG_ID", "").strip()
    pem_b64 = os.getenv("COINBASE_PEM_KEY_B64", "").strip()

    if not key_id or not org_id or not pem_b64:
        raise ValueError("Missing COINBASE_API_KEY_ID, COINBASE_ORG_ID, or COINBASE_PEM_KEY_B64")

    try:
        pem_bytes = base64.b64decode(pem_b64)
    except Exception as e:
        raise ValueError(f"Failed to decode PEM: {e}")

    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,
        "sub": org_id
    }

    token = jwt.encode(payload, pem_bytes, algorithm="ES256", headers={"kid": key_id})
    return token
