# app/nija_client.py
import os, time, jwt, requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Test JWT generation ---
with open(os.environ["COINBASE_PEM_PATH"], "rb") as f:
    key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

iat = int(time.time())
payload = {"sub": os.environ["COINBASE_ORG_ID"], "iat": iat, "exp": iat+300}

token = jwt.encode(payload, key, algorithm="ES256")
print("JWT:", token)

headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-01-01"}
resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers)
print(resp.status_code, resp.text)

# app/nija_client.py

import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Setup logger
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# Load PEM from file and generate JWT
# -----------------------------
pem_path = os.environ["COINBASE_PEM_PATH"]

with open(pem_path, "rb") as pem_file:
    pem_data = pem_file.read()

private_key = serialization.load_pem_private_key(
    pem_data,
    password=None,
    backend=default_backend()
)

iat = int(time.time())
payload = {
    "sub": os.environ["COINBASE_ORG_ID"],  # MUST be Org ID
    "iat": iat,
    "exp": iat + 300  # 5 minutes expiration
}

COINBASE_JWT = jwt.encode(payload, private_key, algorithm="ES256")
logger.info(f"Generated Coinbase JWT: {COINBASE_JWT[:50]}...")

# -----------------------------
# Prepare headers for authenticated requests
# -----------------------------
HEADERS = {
    "Authorization": f"Bearer {COINBASE_JWT}",
    "CB-VERSION": "2025-01-01"
}

# Example request (uncomment to test)
# response = requests.get("https://api.coinbase.com/v2/accounts", headers=HEADERS)
# logger.info(response.json())
