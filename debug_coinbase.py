import os
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from app.nija_client import CoinbaseClient

# Optional: enable detailed JWT debug
os.environ["DEBUG_JWT"] = "1"

def debug_coinbase_client():
    try:
        # Fix PEM formatting from env
        pem_content = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")
        private_key = serialization.load_pem_private_key(
            pem_content.encode(), password=None, backend=default_backend()
        )

        # Initialize Coinbase client
        client = CoinbaseClient()

        # Generate JWT for accounts endpoint
        jwt_token = client._generate_jwt("GET", f"/organizations/{client.org_id}/accounts")
        print("JWT preview:", jwt_token[:200])
        url = f"{client.base_url}/organizations/{client.org_id}/accounts"
        print("Request URL:", url)

        # Make request to Coinbase API
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "CB-VERSION": "2025-11-12"
        }
        resp = requests.get(url, headers=headers)

        print("HTTP status code:", resp.status_code)
        print("Response text:", resp.text[:500])  # truncate for safety

        if resp.status_code != 200:
            logger.error("Failed to fetch accounts. HTTP %s: %s", resp.status_code, resp.text)
        else:
            print("Accounts fetched successfully:", resp.json())

    except Exception as e:
        logger.exception("Error in debug_coinbase_client: %s", e)

if __name__ == "__main__":
    debug_coinbase_client()
