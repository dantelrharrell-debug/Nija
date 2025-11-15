# validate_coinbase_credentials.py
import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=''))

# Load env vars (or set manually here for testing)
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # raw PEM string
COINBASE_JWT_KID = os.getenv("COINBASE_JWT_KID")
SANDBOX = os.getenv("SANDBOX", "1")  # 1 = sandbox, 0 = live

BASE_URL = "https://api-public.sandbox.pro.coinbase.com" if SANDBOX == "1" else "https://api.pro.coinbase.com"

def generate_jwt():
    try:
        import cryptography.hazmat.primitives.serialization as serialization
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        logger.error("cryptography module is missing. Install via `pip install cryptography`")
        return None

    try:
        key = serialization.load_pem_private_key(
            COINBASE_PEM_CONTENT.encode(),
            password=None,
            backend=default_backend()
        )
    except Exception as e:
        logger.error(f"Failed to load PEM: {e}")
        return None

    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "jti": str(time.time())
    }

    try:
        token = jwt.encode(payload, key, algorithm="ES256", headers={"kid": COINBASE_JWT_KID, "alg": "ES256"})
        return token
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        return None

def test_connection():
    token = generate_jwt()
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "CB-ACCESS-KEY": COINBASE_API_KEY,
        "CB-ACCESS-ORG": COINBASE_ORG_ID
    }

    try:
        r = requests.get(f"{BASE_URL}/accounts", headers=headers)
        if r.status_code == 200:
            logger.success("✅ Coinbase credentials are valid!")
            logger.info(r.json())
        else:
            logger.error(f"❌ Coinbase returned {r.status_code}: {r.text}")
    except Exception as e:
        logger.error(f"Request failed: {e}")

if __name__ == "__main__":
    test_connection()
