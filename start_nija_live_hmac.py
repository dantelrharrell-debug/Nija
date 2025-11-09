import os
import time
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# -------------------------
# Config
# -------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
ORG_ID = os.getenv("COINBASE_ORG_ID")  # Required for Advanced API (v3)
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

RETRY_INTERVAL = 5  # seconds

# -------------------------
# HMAC Client
# -------------------------
class CoinbaseHMACClient:
    def __init__(self, base_url, api_key, api_secret):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret

    def request(self, method="GET", path="/v2/accounts", **kwargs):
        url = f"{self.base_url}{path}"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2025-11-08"  # Example API version
        }
        try:
            resp = requests.request(method, url, headers=headers, **kwargs)
        except Exception as e:
            logging.error(f"Request failed: {e}")
            return None, None

        # Handle non-JSON responses safely
        try:
            data = resp.json()
        except Exception:
            data = resp.text

        return resp.status_code, data

# -------------------------
# Fetch accounts safely
# -------------------------
def fetch_accounts(client):
    endpoints = ["/v3/accounts", "/v2/accounts"]  # Try v3 first, then fallback
    for ep in endpoints:
        status, accounts = client.request(path=ep)
        if status == 200:
            logging.info(f"✅ Accounts fetched from {ep}")
            return accounts
        elif status == 401:
            logging.warning(f"⚠️ Unauthorized (401) at {ep}. Check API key/permissions.")
            return None
        elif status == 404:
            logging.warning(f"⚠️ {ep} not found (404), trying next endpoint...")
        else:
            logging.warning(f"⚠️ Failed at {ep}: Status {status}, Response: {accounts}")
    return None

# -------------------------
# Main loop
# -------------------------
def main_loop():
    client = CoinbaseHMACClient(API_BASE, API_KEY, API_SECRET)
    logging.info("HMAC CoinbaseClient initialized.")

    while True:
        accounts = fetch_accounts(client)
        if accounts:
            logging.info(f"Fetched accounts: {accounts}")
            # Add trading logic here
        else:
            logging.error("❌ No HMAC accounts found. Retrying...")
        time.sleep(RETRY_INTERVAL)

# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        logging.error("API_KEY or API_SECRET not set. Aborting.")
    else:
        main_loop()
