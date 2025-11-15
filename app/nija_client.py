import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Setup logger ---
logger.remove()
logger.add(lambda m: print(m, end=""))

# --- Load Coinbase PEM from file ---
try:
    with open(os.environ["COINBASE_PEM_PATH"], "rb") as pem_file:
        pem_data = pem_file.read()
        private_key = serialization.load_pem_private_key(
            pem_data,
            password=None,
            backend=default_backend()
        )
    logger.info("Coinbase PEM loaded successfully")
except Exception as e:
    logger.error(f"Failed to load PEM: {e}")
    raise e

# --- Generate JWT for Coinbase Advanced API ---
def generate_jwt():
    try:
        payload = {
            "sub": os.environ["COINBASE_ORG_ID"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 300  # 5 minutes expiry
        }
        token = jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers={"kid": os.environ["COINBASE_API_KEY"]}
        )
        return token
    except Exception as e:
        logger.error(f"Failed to generate JWT: {e}")
        return None

jwt_token = generate_jwt()
if jwt_token:
    logger.info(f"Generated JWT preview: {jwt_token[:50]}")
else:
    logger.error("JWT generation failed. Coinbase API calls will not work.")
