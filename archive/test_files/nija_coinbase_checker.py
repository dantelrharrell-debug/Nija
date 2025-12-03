# nija_coinbase_checker.py
import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseChecker:
    def __init__(self):
        self.api_key_full = os.getenv("COINBASE_API_KEY_FULL")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem_path = os.getenv("COINBASE_PEM_PATH")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.cb_host = "https://api.coinbase.com"
        self.token = None

    def load_pem(self):
        pem_text = None
        if self.pem_content:
            pem_text = self.pem_content.replace("\\n", "\n").strip().strip('"').strip("'")
        elif self.pem_path and os.path.exists(self.pem_path):
            with open(self.pem_path, "r", encoding="utf-8") as f:
                pem_text = f.read()
        else:
            raise RuntimeError("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

        try:
            self.private_key = serialization.load_pem_private_key(
                pem_text.encode(), password=None, backend=default_backend()
            )
            print("✅ PEM loaded successfully")
        except Exception as e:
            raise RuntimeError(f"❌ Failed to load PEM: {e}")

    def build_jwt(self, path, method="GET"):
        if self.api_key_full:
            kid = self.api_key_full
            sub = self.api_key_full.split("/")[-1]
        else:
            if "/" in (self.api_key or ""):
                kid = self.api_key
                sub = self.api_key.split("/")[-1]
            else:
                kid = self.api_key
                sub = self.api_key

        iat = int(time.time())
        payload = {"iat": iat, "exp": iat + 120, "sub": sub, "request_path": path, "method": method}
        headers = {"alg": "ES256", "kid": kid}
        self.token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
        print("JWT built successfully")
        return self.token

    def test_accounts(self):
        path = f"/api/v3/brokerage/organizations/{self.org_id}/accounts"
        token = self.build_jwt(path)
        headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"}
        try:
            resp = requests.get(f"{self.cb_host}{path}", headers=headers, timeout=10)
        except requests.RequestException as e:
            return False, f"Network error: {e}"

        if resp.status_code == 200:
            return True, resp.json()
        elif resp.status_code == 401:
            return False, "❌ Unauthorized: Check API key, org, permissions, or PEM"
        else:
            return False, f"Unexpected response {resp.status_code}: {resp.text}"

if __name__ == "__main__":
    checker = CoinbaseChecker()
    checker.load_pem()
    success, result = checker.test_accounts()
    if success:
        print("✅ Coinbase accounts fetched successfully")
        print(result)
    else:
        print(result)
