# safe_credential_check.py
import os
import requests
from loguru import logger
from app.nija_client import CoinbaseClient

logger.info("Starting Coinbase credential check...")

try:
    client = CoinbaseClient()
except Exception as e:
    logger.error("Failed to initialize CoinbaseClient: {}", e)
    exit(1)

# Generate JWT and check accounts endpoint
try:
    path = f"/organizations/{client.org_id}/accounts"
    url = client.base_url + path
    jwt_token = client._generate_jwt("GET", path)

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "CB-VERSION": "2025-11-12"
    }

    resp = requests.get(url, headers=headers)

    if resp.status_code == 200:
        logger.success("✅ Coinbase credentials are valid! Accounts fetched successfully.")
    elif resp.status_code == 401:
        logger.error("❌ Unauthorized (401). Check your API key, PEM, and Org ID.")
    else:
        logger.warning("⚠️ Unexpected status code {}: {}", resp.status_code, resp.text[:200])

except Exception as e:
    logger.exception("Exception during credential check: {}", e)
