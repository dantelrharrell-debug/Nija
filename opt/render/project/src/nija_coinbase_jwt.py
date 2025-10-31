# nija_coinbase_jwt.py
import base64
import time
import jwt  # PyJWT
import logging
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

# --- Your keys (set these from env or hardcode for now) ---
COINBASE_API_KEY_ID = "a9dae6d1-8592-4488-92cf-b3309a9ea5f2"
COINBASE_ORG_ID = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
COINBASE_PEM_KEY_B64 = "MHcCAQEEIOrZ/6/2ITZjLZAOYvnu7ZbAIQfDg8VEIP7XaqEAtZacoAoGCCqGSM49AwEHoUQDQgAELvgEIjI5gZyrhPOiZ4dZInphcm901xcHVAjdLmerldf/8agzuS1wOBJUqCeRF/wD/HuHs8fndWQACG7IUILRzw=="

# --- Load PEM key correctly ---
def load_pem_key(pem_b64):
    try:
        pem_bytes = base64.b64decode(pem_b64)
        key = serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())
        return key
    except Exception as e:
        logger.error(f"[NIJA-JWT] Failed to load PEM key: {e}")
        raise

# --- Generate JWT for Coinbase REST ---
def get_jwt_token():
    try:
        private_key = load_pem_key(COINBASE_PEM_KEY_B64)
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 60,  # short-lived token
            "sub": COINBASE_ORG_ID,
        }
        token = jwt.encode(payload, private_key, algorithm="ES256")
        logger.info(f"[NIJA-JWT] JWT token preview (first 20 chars): {token[:20]}")
        return token
    except Exception as e:
        logger.error(f"[NIJA-JWT] Failed to generate JWT: {e}")
        return None
