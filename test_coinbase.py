#!/usr/bin/env python3
import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""))

# Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

def fix_pem(pem_raw):
    if not pem_raw:
        return None
    pem = pem_raw.strip().replace("\\n", "\n")
    if not pem.startswith("-----BEGIN EC PRIVATE KEY-----"):
        pem = "-----BEGIN EC PRIVATE KEY-----\n" + pem
    if not pem.strip().endswith("-----END EC PRIVATE KEY-----"):
        pem = pem + "\n-----END EC PRIVATE KEY-----"
    return pem

def generate_jwt(pem, kid, org_id):
    if not pem or not kid or not org_id:
        logger.error("Missing PEM, KID, or ORG_ID for JWT generation")
        return None
    now = int(time.time())
    payload = {"iat": now, "exp": now + 300, "sub": org_id}
    headers = {"kid": kid}
    try:
        token = jwt.encode(payload, pem, algorithm="ES256", headers=headers)
        logger.info("JWT generated: %s", token[:60])
        return token
    except Exception as e:
        logger.error("JWT generation failed: %s", e)
        return None

def test_coinbase_api(token, org_id):
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{org_id}/accounts"
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-01",
        "User-Agent": "nija-test/1.0"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        logger.info("Status Code: %s", resp.status_code)
        logger.info("Response Body (truncated 500 chars):\n%s", resp.text[:500])
    except Exception as e:
        logger.error("HTTP request failed: %s", e)

def main():
    logger.info("Starting Coinbase test...")
    fixed_pem = fix_pem(PEM_RAW)
    if not fixed_pem:
        logger.error("PEM is missing or invalid")
        return
    jwt_token = generate_jwt(fixed_pem, API_KEY, ORG_ID)
    if not jwt_token:
        logger.error("Cannot generate JWT")
        return
    test_coinbase_api(jwt_token, ORG_ID)
    logger.info("Test complete")

if __name__ == "__main__":
    main()
