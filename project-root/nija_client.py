# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import jwt  # only needed if using JWT auth

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Passphrase is optional now for Advanced API
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise ValueError("❌ COINBASE_API_KEY or COINBASE_API_SECRET not set in environment variables")

        if not self.api_passphrase:
            print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Coinbase Advanced API.")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

        # Only add passphrase if it exists (legacy API)
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase

        return headers

    def get_accounts(self):
        """Fetch accounts from Coinbase. Gracefully handles 401/403."""
        url = f"{self.base_url}/v2/accounts"
        headers = self._get_headers("GET", "/v2/accounts")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code in (401, 403):
                print("❌ Unauthorized: check your API key/secret. Passphrase is not needed for Advanced API.")
                return None
            raise e
        except Exception as e:
            print(f"❌ Error fetching accounts: {e}")
            return None

# ================================
# Railway/Render-safe debug runner
# ================================
if __name__ == "__main__":
    print("ℹ️ Starting CoinbaseClient debug check...")

    missing = []
    for key in ["COINBASE_API_KEY", "COINBASE_API_SECRET"]:
        if not os.getenv(key):
            missing.append(key)

    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
    else:
        if not os.getenv("COINBASE_API_PASSPHRASE"):
            print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Advanced API.")
        print("✅ Required environment variables are set.")

        try:
            client = CoinbaseClient()
            accounts = client.get_accounts()
            if accounts is not None:
                print("✅ CoinbaseClient test successful. Accounts fetched:")
                print(accounts)
            else:
                print("⚠️ CoinbaseClient test did not fetch accounts (check API key/secret).")
        except Exception as e:
            print(f"❌ Error initializing CoinbaseClient: {e}")
