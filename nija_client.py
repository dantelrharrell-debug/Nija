import os
import time
import json
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

        # --- Validate ---
        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase credentials: COINBASE_API_KEY or COINBASE_API_SECRET")

        # --- Initialize Coinbase REST client (no passphrase needed) ---
        self.client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)

        logger.info("✅ CoinbaseClient initialized successfully (no passphrase required).")

    # ---------------------------------------------------------
    # Generic GET request helper
    # ---------------------------------------------------------
    def _send_request(self, endpoint: str, method="GET", params=None):
        """Send HTTP request to Coinbase API (handles auth and errors)."""
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

    # ---------------------------------------------------------
    # Fetch all accounts
    # ---------------------------------------------------------
    def get_all_accounts(self):
        """Return all Coinbase account balances."""
        try:
            data = self._send_request("/v2/accounts")
            return data
        except Exception as e:
            log.error(f"Failed to fetch accounts: {e}")
            raise RuntimeError(f"Failed to fetch accounts: {e}")

    # ---------------------------------------------------------
    # Fetch USD balance (spot)
    # ---------------------------------------------------------
    def get_usd_spot_balance(self):
        """Return USD spot balance from Coinbase."""
        try:
            accounts = self.get_all_accounts()
            usd_accounts = [
                acct for acct in accounts.get("data", []) if acct["balance"]["currency"] == "USD"
            ]
            if not usd_accounts:
                raise RuntimeError("No USD account found.")
            balance = float(usd_accounts[0]["balance"]["amount"])
            logger.info(f"💵 USD Spot Balance: {balance}")
            return balance
        except Exception as e:
            log.error(f"❌ Failed to fetch USD Spot balance: {e}")
            raise RuntimeError(f"Failed to fetch USD Spot balance: {e}")

    # ---------------------------------------------------------
    # Place order (simple market)
    # ---------------------------------------------------------
    def place_market_order(self, product_id="BTC-USD", side="buy", funds=10.0):
        """Place a simple market order on Coinbase."""
        try:
            payload = {
                "side": side,
                "product_id": product_id,
                "funds": str(funds),
                "type": "market",
            }
            response = self.client.orders.create_order(**payload)
            logger.info(f"✅ Market order placed: {side} {funds} {product_id}")
            return response
        except Exception as e:
            log.error(f"❌ Failed to place order: {e}")
            raise RuntimeError(f"Failed to place order: {e}")


# ---------------------------------------------------------
# Standalone debug check (when run directly)
# ---------------------------------------------------------
if __name__ == "__main__":
    log.info("🔍 [DEBUG] Starting CoinbaseClient test...")
    try:
        client = CoinbaseClient()
        usd_balance = client.get_usd_spot_balance()
        log.info(f"✅ USD Balance: {usd_balance}")
    except Exception as e:
        log.error(f"❌ Error during client debug: {e}")
