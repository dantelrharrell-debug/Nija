#!/usr/bin/env python3
import os
import time
import requests
import jwt as pyjwt
from loguru import logger

logger.info("=== Nija Coinbase Advanced API Test ===")

# Load environment variables
pem = os.getenv("COINBASE_PEM_CONTENT")
iss = os.getenv("COINBASE_ISS")
base = os.getenv("COINBASE_BASE")  # Example: https://api.cdp.coinbase.com

if not pem or not iss or not base:
    logger.error("❌ Missing COINBASE_PEM_CONTENT, COINBASE_ISS, or COINBASE_BASE")
    exit(1)

# Generate ephemeral JWT (valid 5 minutes)
try:
    now = int(time.time())
    payload = {"iat": now, "exp": now + 300, "iss": iss}
    token = pyjwt.encode(payload, pem, algorithm="ES256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    logger.info("✅ JWT generated successfully")
except Exception as e:
    logger.error("❌ Failed to generate JWT:", e)
    exit(1)

# Endpoints to test
endpoints = [
    "/api/v3/brokerage/accounts",  # Advanced API
    "/accounts",                   # Standard fallback
]

for path in endpoints:
    url = base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Request to {url} returned status {r.status_code}")
        try:
            data = r.json()
            logger.info("Response JSON:", data)
        except Exception:
            logger.info("Response text:", r.text)
    except requests.RequestException as e:
        logger.error(f"Request failed for {url}:", e)

logger.info("✅ Test complete. If 200 OK, your keys and JWT are valid.")
