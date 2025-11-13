import os
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt, base64
from app.nija_client import CoinbaseClient

# Optional: enable detailed JWT debug
os.environ["DEBUG_JWT"] = "1"

def debug_coinbase_jwt():
    try:
        # Initialize client
        client = CoinbaseClient()

        # Load API key and PEM explicitly (for logging/debug)
        api_key_id = os.environ.get("COINBASE_API_KEY")
        pem_content = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")

        if not api_key_id:
            logger.error("COINBASE_API_KEY not set!")
        if not pem_content:
            logger.error("COINBASE_PEM not set or empty!")

        try:
            private_key = serialization.load_pem_private_key(
                pem_content.encode(), password=None, backend=default_backend()
            )
            logger.info("Private key loaded successfully")
        except Exception as e:
            logger.exception("Failed to load private key: %s", e)

        # Build request path and URL
        path = f"/api/v3/brokerage/organizations/{client.org_id}/accounts"
        url = client.base_url + path

        # Generate JWT
        jwt_token = client._generate_jwt("GET", path)

        # Print JWT and request info
        print("JWT:", jwt_token)
        print("Request path:", path)
        print("Request URL:", url)

        # Decode JWT to inspect header and payload
        header_b64, payload_b64, signature_b64 = jwt_token.split('.')
        header_json = base64.urlsafe_b64decode(header_b64 + "==").decode()
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        logger.info("JWT Header: %s", header_json)
        logger.info("JWT Payload: %s", payload_json)

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
