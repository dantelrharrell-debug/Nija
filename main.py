import os
import time
import datetime
import requests
import jwt  # PyJWT
from loguru import logger

def debug_coinbase_jwt_test():
    """
    Debug function to generate a valid JWT and call Coinbase /accounts.
    Prints JWT preview, HTTP status, and body.
    """
    logger.info("=== DEBUG: generating JWT and calling Coinbase /accounts ===")

    # --- Load Coinbase env vars ---
    COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
    COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")  # short UUID
    COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")        # full path
    COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

    if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT]):
        logger.error("Coinbase env vars missing! Check .env")
        return

    # Fix PEM formatting if stored as single line
    private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n")

    # --- Build request info ---
    coinbase_path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    method = "GET"

    # --- Generate JWT ---
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,  # token valid for 2 minutes
        "sub": COINBASE_API_SUB,  # full path
        "request_path": coinbase_path,
        "method": method,
        "jti": f"dbg-{iat}"
    }

    headers_jwt = {
        "alg": "ES256",
        "kid": COINBASE_API_KEY_ID,  # short UUID
        "typ": "JWT"
    }

    try:
        token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
        logger.info("DEBUG JWT (preview): {}", token[:200])
    except Exception as e:
        logger.exception("Failed to generate JWT: {}", e)
        return

    # --- Call Coinbase API ---
    url = "https://api.coinbase.com" + coinbase_path
    try:
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, timeout=10)

        logger.info("DEBUG /accounts status: {}", resp.status_code)
        logger.info("DEBUG /accounts body: {}", resp.text)
    except Exception as e:
        logger.exception("Failed to call Coinbase /accounts: {}", e)

    logger.info("=== DEBUG complete ===")
