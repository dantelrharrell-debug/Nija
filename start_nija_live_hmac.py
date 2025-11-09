import os
import requests
import logging
import asyncio

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("__main__")

# --- Environment Variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
ORG_ID = os.getenv("COINBASE_ORG_ID")  # For Advanced HMAC
API_BASE_ADV = "https://api.cdp.coinbase.com"
API_BASE_RETAIL = "https://api.coinbase.com"

# --- Determine API Base ---
USE_ADVANCED = bool(ORG_ID)
API_BASE = API_BASE_ADV if USE_ADVANCED else API_BASE_RETAIL
logger.info(f"Using {'Advanced' if USE_ADVANCED else 'Retail'} Coinbase API.")

# --- HMAC Coinbase Client ---
class CoinbaseClient:
    def __init__(self, api_key, api_secret, org_id=None, base_url=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.org_id = org_id
        self.base_url = base_url
        logger.info("HMAC CoinbaseClient initialized.")

    def request(self, method="GET", path="/v3/accounts"):
        url = f"{self.base_url}{path}"
        headers = {"CB-ACCESS-KEY": self.api_key}
        if self.org_id:
            headers["CB-ACCESS-ORG-ID"] = self.org_id

        try:
            response = requests.request(method, url, headers=headers)
            try:
                data = response.json()
            except Exception:
                logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
                return response.status_code, None
            return response.status_code, data
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None, None

# --- Fetch Accounts with Auto Fallback ---
def fetch_hmac_accounts():
    client = CoinbaseClient(API_KEY, API_SECRET, ORG_ID, API_BASE)
    endpoints = ["/v3/accounts", "/v2/accounts"] if USE_ADVANCED else ["/v2/accounts"]

    for endpoint in endpoints:
        status, accounts = client.request(method="GET", path=endpoint)
        if status == 404:
            logger.warning(f"{endpoint} not found (404). Trying next endpoint...")
            continue
        if accounts:
            logger.info(f"✅ Fetched {len(accounts)} accounts from {endpoint}.")
            return accounts
        else:
            logger.warning(f"No accounts returned from {endpoint}. Status: {status}")
    # If all endpoints fail
    logger.error("❌ No HMAC accounts found on any endpoint.")
    return []

# --- Main Bot Loop ---
async def main_loop():
    logger.info("Starting HMAC live bot...")
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.error("Aborting bot: no accounts available.")
        return

    # Placeholder: Replace with your live trading logic
    while True:
        logger.info("Bot running... (replace this with trade logic)")
        await asyncio.sleep(10)

# --- Run Bot ---
if __name__ == "__main__":
    asyncio.run(main_loop())
