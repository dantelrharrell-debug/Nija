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
if ORG_ID:
    API_BASE = API_BASE_ADV
    USE_ADVANCED = True
    logger.info("Using Coinbase Advanced API (HMAC v3).")
else:
    API_BASE = API_BASE_RETAIL
    USE_ADVANCED = False
    logger.info("Using Coinbase Retail API (HMAC v2).")

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

# --- Fetch Accounts Gracefully ---
def fetch_hmac_accounts():
    client = CoinbaseClient(API_KEY, API_SECRET, ORG_ID, API_BASE)
    endpoint = "/v3/accounts" if USE_ADVANCED else "/v2/accounts"

    status, accounts = client.request(method="GET", path=endpoint)

    if status == 404:
        logger.warning(f"{endpoint} not found (404). Trying fallback...")
        if USE_ADVANCED:
            # Advanced fallback to v2 if v3 fails
            status, accounts = client.request(method="GET", path="/v2/accounts")

    if not accounts:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return []

    logger.info(f"✅ Fetched {len(accounts)} accounts.")
    return accounts

# --- Main Bot Loop ---
async def main_loop():
    logger.info("Starting HMAC live bot...")
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.error("No HMAC accounts found. Aborting bot.")
        return

    # Placeholder: Replace with your live trading logic
    while True:
        logger.info("Bot running... (replace this with trade logic)")
        await asyncio.sleep(10)

# --- Run Bot ---
if __name__ == "__main__":
    asyncio.run(main_loop())
