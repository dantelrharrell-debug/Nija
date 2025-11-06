import os
import time
import jwt
import requests

class CoinbaseJWTClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")  # PEM as single-line string with \n
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not self.api_key or not self.pem_content:
            raise ValueError("COINBASE_API_KEY or COINBASE_PEM_CONTENT not set!")

        # Convert single-line PEM to proper multi-line if needed
        self.pem_key = self.pem_content.replace("\\n", "\n")

    def generate_jwt(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # token valid for 5 minutes
            "sub": self.api_key
        }
        token = jwt.encode(payload, self.pem_key, algorithm="RS256")
        return token

    def request(self, method, path, data=None):
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.generate_jwt()}"}

        if method.upper() == "GET":
            r = requests.get(url, headers=headers, params=data)
        elif method.upper() == "POST":
            r = requests.post(url, headers=headers, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if r.status_code >= 400:
            raise Exception(f"Coinbase API error {r.status_code}: {r.text}")

        return r.json()

    # Example helper to list accounts
    def list_accounts(self):
        return self.request("GET", "/platform/v2/accounts")
