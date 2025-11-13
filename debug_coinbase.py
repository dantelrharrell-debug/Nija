import os
import requests
import jwt
import base64
from loguru import logger
from app.nija_client import CoinbaseClient

# Optional: enable detailed JWT debug
os.environ["DEBUG_JWT"] = "1"

def debug_coinbase_jwt():
    try:
        # Initialize Coinbase client
        client = CoinbaseClient()

        # Build request path and URL
        path = f"/api/v3/brokerage/organizations/{client.org_id}/accounts"
        url = client.base_url + path

        # Generate JWT
        jwt_token = client._generate_jwt("GET", path)

        # Decode JWT for inspection
        header_b64, payload_b64, signature_b64 = jwt_token.split('.')
        header_json = base64.urlsafe_b64decode(header_b64 + "==").decode()
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()

        # Print debug info
        print("JWT:", jwt_token)
        print("JWT Header:", header_json)
        print("JWT Payload:", payload_json)
        print("Request path:", path)
        print("Request URL:", url)

        # Make the request
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {jwt_token}",
            "CB-VERSION": "2025-11-12"
        })

        print("HTTP status code:", resp.status_code)
        print("Response text:", resp.text[:500])  # truncate for safety

        if resp.status_code != 200:
            logger.error("Failed to fetch accounts. HTTP %s: %s", resp.status_code, resp.text)
        else:
            print("Accounts fetched successfully:", resp.json())

    except Exception as e:
        logger.exception("Error in debug_coinbase_jwt: %s", e)

if __name__ == "__main__":
    debug_coinbase_jwt()
