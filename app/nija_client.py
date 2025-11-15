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
PEM_PATH = os.environ.get("COINBASE_PEM_PATH")
if not PEM_PATH:
    logger.error("COINBASE_PEM_PATH not set")
    raise ValueError("COINBASE_PEM_PATH environment variable missing")

with open(PEM_PATH, "rb") as pem_file:
    pem_data = pem_file.read()
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=None,
        backend=default_backend()
    )

# --- Environment variables ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not COINBASE_API_KEY or not COINBASE_ORG_ID:
    logger.error("Missing Coinbase API Key or Org ID")
    raise ValueError("Missing Coinbase API Key or Org ID")

# --- Generate JWT ---
current_ts = int(time.time())
payload = {
    "sub": COINBASE_ORG_ID,          # Your organization ID
    "iat": current_ts,               # Issued at timestamp
    "exp": current_ts + 300          # Expires in 5 minutes
}

headers = {
    "alg": "ES256",
    "kid": COINBASE_API_KEY
}

jwt_token = jwt.encode(
    payload,
    private_key,
    algorithm="ES256",
    headers=headers
)

logger.info(f"Generated JWT: {jwt_token[:50]}...")

# --- Test Coinbase API call ---
url = "https://api.coinbase.com/v2/accounts"
response = requests.get(url, headers={"Authorization": f"Bearer {jwt_token}"})

if response.status_code == 200:
    logger.success("✅ Coinbase connection successful!")
    logger.info(response.json())
else:
    logger.error(f"❌ Coinbase connection failed: {response.status_code}")
    logger.error(response.text)
