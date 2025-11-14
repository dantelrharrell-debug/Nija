# test_jwt.py
import os
import base64
import time
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

def test_jwt():
    org_id = os.environ.get("COINBASE_ORG_ID")
    pem_b64 = os.environ.get("COINBASE_PEM_B64")

    if not pem_b64 or not org_id:
        logger.error("Missing COINBASE_PEM_B64 or COINBASE_ORG_ID")
        return

    # Decode PEM
    pem_bytes = base64.b64decode(pem_b64)

    # Load private key
    private_key = serialization.load_pem_private_key(
        pem_bytes,
        password=None,
        backend=default_backend()
    )

    # Generate JWT
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,
        "sub": org_id
    }

    token = jwt.encode(payload, private_key, algorithm="ES256")
    logger.info(f"JWT generated successfully: {token[:30]}...")  # partial for security

if __name__ == "__main__":
    test_jwt()
