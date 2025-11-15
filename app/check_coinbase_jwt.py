import os
import jwt
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Setup logger
logger.remove()
logger.add(lambda msg: print(msg, flush=True), level="INFO")

# Load environment variables
API_KEY = os.environ.get("COINBASE_API_KEY")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")

if not API_KEY or not ORG_ID or not PEM_CONTENT:
    logger.error("One or more environment variables are missing!")
    exit(1)

logger.info("Environment variables loaded")

# Clean PEM (ensure newlines)
PEM_CONTENT = PEM_CONTENT.replace("\\n", "\n")

# Load PEM key
private_key = serialization.load_pem_private_key(
    PEM_CONTENT.encode(),
    password=None,
    backend=default_backend()
)

# Generate JWT
iat = int(time.time())
payload = {
    "iat": iat,
    "jti": str(iat),
    "sub": ORG_ID,
    "exp": iat + 30,  # short expiration
}
token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": API_KEY})
logger.info(f"Generated JWT:\n{token[:50]}...")  # preview only

# Test Coinbase API
url = "https://api.coinbase.com/v2/accounts"
headers = {"Authorization": f"Bearer {token}"}
try:
    r = requests.get(url, headers=headers)
    logger.info(f"Coinbase API status: {r.status_code}")
    if r.status_code != 200:
        logger.error(f"API response: {r.text}")
    else:
        logger.info("Coinbase API connection successful!")
except Exception as e:
    logger.exception(f"API request failed: {e}")
