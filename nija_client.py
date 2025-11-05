import os
import logging
import requests
from coinbase.rest import RESTClient
from loguru import logger

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")


class CoinbaseClient:
    def __init__(self):
        # --- Load API credentials from environment ---
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # --- Validate credentials ---
        if not all([self.api_key, self.api_secret]):
            raise RuntimeError(
                "❌ Missing Coinbase credentials: COINBASE_API_KEY or COINBASE_API_SECRET"
            )

        # --- Initialize Coinbase REST client (no passphrase) ---
        self.client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)
        logger.info("✅ CoinbaseClient initialized successfully (no passphrase required).")

    # ---------------------------
    # Generic GET request helper
    # ---------------------------
    def _send_request(self, endpoint: str, method="GET", params=None):
        url = f"{self.base_url}{endpoint}"
        headers = {"CB-VERSION": "2021-11-01"}
        response = requests.request(method, url, headers=headers, params=params)
        if response.status_code == 401:
            raise RuntimeError(
                "❌ 401 Unauthorized. Check API key permissions (View + Trade) and confirm it’s an Advanced/Base key."
            )
        elif not response.ok:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    # ---------------------------
    # Fetch all accounts
    # ---------------------------
    def get_all_accounts(self):
        try:
            data = self._send_request("/v2/accounts")
            return data.get("data", [])
        except Exception as e:
            log.error(f"Failed to fetch accounts: {e}")
            raise

    # ---------------------------
    # Fetch USD spot balance
    # ---------------------------
    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        usd_accounts = [acct for acct in accounts if acct["balance"]["currency"] == "USD"]
        if not usd_accounts:
            raise RuntimeError("No USD account found.")
        balance = float(usd_accounts[0]["balance"]["amount"])
        logger.info(f"💵 USD Spot Balance: {balance}")
        return balance

    # ---------------------------
    # Place market order
    # ---------------------------
    def place_market_order(self, product_id="BTC-USD", side="buy", funds=10.0):
        try:
            payload = {"side": side, "product_id": product_id, "funds": str(funds), "type": "market"}
            response = self.client.orders.create_order(**payload)
            logger.info(f"✅ Market order placed: {side} {funds} {product_id}")
            return response
        except Exception as e:
            log.error(f"❌ Failed to place order: {e}")
            raise


# ---------------------------
# Backwards-compatible top-level helpers
# ---------------------------
def get_all_accounts():
    client = CoinbaseClient()
    return client.get_all_accounts()


def get_usd_spot_balance():
    client = CoinbaseClient()
    return client.get_usd_spot_balance()
