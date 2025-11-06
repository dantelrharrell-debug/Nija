import os
import time
import jwt
import requests

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        if not all([self.api_key, self.api_secret]):
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set.")

        self.jwt_token = self.generate_jwt()

    def generate_jwt(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300  # 5 minutes expiry
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.jwt_token}",
            "CB-ACCESS-KEY": self.api_key,
            "Content-Type": "application/json"
        }

    def list_accounts(self):
        url = f"{self.base_url}/platform/v2/evm/accounts"
        response = requests.get(url, headers=self.get_headers())
        if response.status_code != 200:
            return {"ok": False, "status": response.status_code, "payload": response.text}
        return {"ok": True, "accounts": response.json()}

# Quick test
if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.list_accounts()
    print(accounts)
