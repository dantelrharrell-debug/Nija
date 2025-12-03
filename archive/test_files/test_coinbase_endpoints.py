#!/usr/bin/env python3
# test_coinbase_endpoints.py
import os, time, requests
import jwt as pyjwt
from loguru import logger

logger.add(lambda msg: print(msg, end=""))

pem = os.getenv("COINBASE_PEM_CONTENT")
iss = os.getenv("COINBASE_ISS")
base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com").rstrip("/")

if not pem or not iss:
    logger.error("Missing COINBASE_PEM_CONTENT or COINBASE_ISS in env. Set them and re-run.")
    raise SystemExit(1)

# create ephemeral JWT
now = int(time.time())
payload = {"iat": now, "exp": now + 240, "iss": iss}
try:
    token = pyjwt.encode(payload, pem, algorithm="ES256", headers={"alg":"ES256"})
    if isinstance(token, bytes): token = token.decode("utf-8")
    logger.info("✅ Generated JWT (first 64 chars): " + token[:64])
except Exception as e:
    logger.error("Failed to create JWT: %s" % e)
    raise

headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-09"}

endpoints = [
    (f"{base}/api/v3/brokerage/accounts", "Advanced brokerage (api/v3/brokerage/accounts)"),
    (f"{base}/accounts", "Fallback /accounts"),
    ("https://api.coinbase.com/v2/accounts", "Classic v2/accounts (requires HMAC)")
]

for url, label in endpoints:
    try:
        logger.info(f"\n-> Requesting {label} -> {url}")
        resp = requests.get(url, headers=headers if "coinbase.com/v2" not in url else {}, timeout=12)
        logger.info(f"Status: {resp.status_code}")
        body = resp.text
        # show short body for debug
        logger.info("Body (first 800 chars):\n" + (body[:800] if body else "<empty>"))
    except requests.RequestException as e:
        logger.error(f"Request to {url} failed: {e}")
