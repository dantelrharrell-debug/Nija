# test_coinbase.py
import os
import requests
from loguru import logger
from app.nija_client import CoinbaseClient

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

try:
    logger.info("Initializing CoinbaseClient...")
    client = CoinbaseClient()
    logger.info("Client initialized with org ID: {}", client.org_id)

    # --- JWT preview ---
    jwt_token = client._generate_jwt("GET", f"/organizations/{client.org_id}/accounts")
    logger.info("JWT preview (first 200 chars): {}", jwt_token[:200])

    # --- Test API request ---
    path = f"/organizations/{client.org_id}/accounts"
    url = client.base_url + path
    headers = {
        "Authorization": f"Bearer {client._generate_jwt('GET', path)}",
        "CB-VERSION": "2025-11-12"
    }

    logger.info("Sending GET request to Coinbase /accounts...")
    resp = requests.get(url, headers=headers)
    logger.info("HTTP status code: {}", resp.status_code)
    logger.info("Response text (first 500 chars): {}", resp.text[:500])

except Exception as e:
    logger.exception("Error during test:")
