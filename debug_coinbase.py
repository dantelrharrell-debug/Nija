import os
import requests
from loguru import logger
from app.nija_client import CoinbaseClient

# Optional: enable detailed JWT debug
os.environ["DEBUG_JWT"] = "1"

def debug_coinbase_jwt():
    try:
        client = CoinbaseClient()

        # Use the full API path as required by Coinbase JWT auth
        path = f"/api/v3/brokerage/organizations/{client.org_id}/accounts"
        url = client.base_url + path

        # Generate JWT using full path
        jwt_token = client._generate_jwt("GET", path)

        # Print debug info
        print("JWT:", jwt_token)
        print("Request path:", path)
        print("Request URL:", url)

        # Make the GET request with JWT
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
