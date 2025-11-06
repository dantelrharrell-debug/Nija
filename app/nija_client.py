import os
import time
import jwt
import requests
from loguru import logger

# ===============================
# CONFIG / ENV VARIABLES
# ===============================
CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET")
CDP_API_BASE = "https://api.cdp.coinbase.com"

if not CDP_API_KEY_ID or not CDP_API_KEY_SECRET:
    logger.error("Coinbase CDP credentials not detected!")
    raise SystemExit(1)

logger.info("✅ All Coinbase credentials detected.")

# ===============================
# JWT GENERATION FUNCTION
# ===============================
def generate_jwt(method: str, path: str, body: str = "") -> str:
    """
    Generate a short-lived JWT for Coinbase CDP v2 API.
    """
    iat = int(time.time())
    exp = iat + 120  # JWT valid for 2 minutes

    payload = {
        "sub": CDP_API_KEY_ID,
        "iat": iat,
        "exp": exp,
        "requestMethod": method.upper(),
        "requestPath": path,
        "requestBody": body
    }

    token = jwt.encode(
        payload,
        CDP_API_KEY_SECRET,
        algorithm="ES256"
    )

    return token

# ===============================
# MAKE AUTHENTICATED REQUEST
# ===============================
def cdp_request(method: str, path: str, body: str = "") -> dict:
    """
    Make an authenticated request to Coinbase CDP v2.
    """
    jwt_token = generate_jwt(method, path, body)
    headers = {"Authorization": f"Bearer {jwt_token}"}

    url = f"{CDP_API_BASE}{path}"

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, data=body)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if response.status_code == 401:
            logger.error("❌ Coinbase API Unauthorized (401). Check JWT and key permissions.")
        else:
            logger.info(f"Response status: {response.status_code}")

        return response.json()

    except Exception as e:
        logger.exception(f"Request failed: {e}")
        return {}

# ===============================
# EXAMPLE USAGE
# ===============================
if __name__ == "__main__":
    path = "/platform/v2/accounts"  # Adjust for the endpoint you need
    result = cdp_request("GET", path)
    logger.info(f"Accounts result: {result}")
