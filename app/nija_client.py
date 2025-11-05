import os
import requests
import time
import jwt

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Coinbase API credentials missing in environment variables.")

    def get_funded_account(self):
        # Example call to get accounts
        url = f"{self.base_url}/v2/accounts"
        headers = {"Authorization": f"Bearer {self._generate_jwt('GET', '/v2/accounts', '')}"}
        response = requests.get(url, headers=headers)
        if response.ok:
            accounts = response.json().get("data", [])
            for account in accounts:
                balance = float(account.get("balance", {}).get("amount", 0))
                if balance > 0:
                    return account
            return None
        else:
            print(f"❌ Failed to fetch accounts: {response.status_code} {response.text}")
            return None

    def _generate_jwt(self, method, endpoint, body):
        # Placeholder for actual JWT generation
        return "FAKE_JWT_TOKEN"

def calculate_position_size(balance, risk_factor=5):
    return balance * (risk_factor / 100)
