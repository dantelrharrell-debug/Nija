import os
import requests
from loguru import logger
from app.nija_client import CoinbaseClient

# Optional: enable detailed JWT debug
os.environ["DEBUG_JWT"] = "1"

def debug_coinbase_client():
    try:
        # Initialize Coinbase client
        client = CoinbaseClient()

        # Show JWT preview
        jwt_token = client._generate_jwt("GET", f"/organizations/{client.org_id}/accounts")
        print("JWT preview:", jwt_token[:200])
        print("Request URL:", f"{client.base_url}/organizations/{client.org_id}/accounts")

        # Test request to accounts endpoint
        path = f"/organizations/{client.org_id}/accounts"
        url = client.base_url + path
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
