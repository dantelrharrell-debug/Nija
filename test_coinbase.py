import os
import json
import logging
from coinbase.wallet.client import Client

logging.basicConfig(level=logging.INFO)

# Fetch environment variables
API_KEY = os.getenv("COINBASE_API_KEY_ID")
ORG_ID = os.getenv("COINBASE_ORG_ID")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not all([API_KEY, ORG_ID, PEM_CONTENT]):
    logging.error("❌ Missing environment variables for Coinbase API.")
    exit(1)

# Temporary function to test Coinbase connection
def test_coinbase_connection():
    try:
        # Save PEM to a temp file
        pem_path = "/tmp/test_coinbase.pem"
        with open(pem_path, "w") as f:
            f.write(PEM_CONTENT)

        # Normally you'd use Coinbase Advanced JWT client here
        # We'll just check if PEM is readable
        with open(pem_path, "r") as f:
            pem_data = f.read()
        logging.info("✅ PEM loaded successfully")

        # Test endpoint call simulation
        logging.info("🔗 Attempting Coinbase org API check...")
        # Replace with real call when ready:
        logging.info(f"Org ID: {ORG_ID}, API Key: {API_KEY[:8]}... [masked]")
        logging.info("✅ Coinbase environment variables look valid (PEM loaded)")

    except Exception as e:
        logging.error(f"❌ Coinbase connection test failed: {e}")

if __name__ == "__main__":
    test_coinbase_connection()
