# nija_coinbase_jwt.py
import base64
import time
import jwt  # PyJWT
import logging
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger("nija_coinbase_jwt")

# Keys from environment or config
COINBASE_API_KEY_ID = "a9dae6d1-8592-4488-92cf-b3309a9ea5f2"
COINBASE_ORG_ID = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
COINBASE_PEM_KEY_B64 = (
    "MHcCAQEEIOrZ/6/2ITZjLZAOYvnu7ZbAIQfDg8VEIP7XaqEAtZacoAoGCCqGSM49AwEHoUQDQgAELvgEIjI5gZyrhPOiZ4dZInphcm901xcHVAjdLmerldf/8agzuS1wOBJUqCeRF/wD/HuHs8fndWQACG7IUILRzw=="
)

def get_private_key():
    try:
        key_bytes = base64.b64decode(COINBASE_PEM_KEY_B64)
        private_key = serialization.load_der_private_key(
            key_bytes,
            password=None,
        )
        return private_key
    except Exception as e:
        logger.error(f"[NIJA-JWT] Failed to load PEM key: {e}")
        raise

def get_jwt_token():
    try:
        private_key = get_private_key()
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes
            "sub": COINBASE_API_KEY_ID,
            "org_id": COINBASE_ORG_ID,
        }
        token = jwt.encode(payload, private_key, algorithm="ES256")
        logger.info(f"[NIJA-JWT] JWT token generated successfully")
        return token
    except Exception as e:
        logger.error(f"[NIJA-JWT] Failed to generate JWT: {e}")
        raise
