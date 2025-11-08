import os
import time
import hmac
import hashlib
import requests
from loguru import logger

class CoinbaseClient:
    """
    Safe CoinbaseClient for both Standard and Advanced API.
    Only changes endpoint to Advanced API so Nija can read funded accounts.
    No trading or other logic changed.
    """

    def __init__(self, advanced=True):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.advanced = advanced

        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API key and secret must be set")
        if not advanced and not self.passphrase:
            raise ValueError("Coinbase API passphrase must be set for standard API")

        logger.success(f"CoinbaseClient initialized (Advanced={self.advanced})")

    def get_accounts(self):
        """
        Fetch accounts safely.
        Uses correct endpoint for Advanced API so Nija can see funded account.
        """
        try:
            if self.advanced:
                url = f"{self.base_url}/platform/v2/evm/accounts"  # correct Advanced API endpoint
            else:
                url = f"{self.base_url}/v2/accounts"  # standard Coinbase API

            timestamp = str(int(time.time()))
            method = "GET"
            request_path = url.replace(self.base_url, "")
            body = ""

            message = timestamp + method + request_path + body
            signature = hmac.new(
                self.api_secret.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()

            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
            }

            # Only add passphrase if standard API
            if not self.advanced and self.passphrase:
                headers["CB-ACCESS-PASSPHRASE"] = self.passphrase

            response = requests.get(url, headers=headers)
            response.raise_for_status()
            accounts = response.json()
            logger.success("Accounts fetched successfully")
            return accounts

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error while fetching accounts: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching accounts: {e}")
            return None


if __name__ == "__main__":
    # quick test to confirm we can see funded accounts
    client = CoinbaseClient(advanced=True)
    accounts = client.get_accounts()
    if accounts:
        logger.info(accounts)
    else:
        logger.warning("No accounts returned. Check API keys and network.")
