import os
import tempfile
import time
import jwt
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.coinbase.jwt")

# --- Create a temporary PEM file from env ---
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if not pem_content:
    raise ValueError("COINBASE_PEM_CONTENT not set in .env")

temp_pem = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
temp_pem.write(pem_content.encode())
temp_pem.flush()
temp_pem_path = temp_pem.name

# --- Coinbase JWT Client ---
class CoinbaseJWTClient:
    def __init__(self):
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.org_id = os.getenv("COINBASE_ISS")
        self.pem_path = temp_pem_path  # use temporary PEM file

        if not self.org_id or not self.pem_path:
            raise Exception("Set COINBASE_ISS and COINBASE_PEM_CONTENT in your environment")

        # Read private key from temp file
        with open(self.pem_path, "r") as f:
            self.private_key = f.read()

        logger.info("CoinbaseJWTClient initialized. Org: %s", self.org_id)

    def generate_jwt(self, method="GET", path="/platform/v1/wallets"):
        now_ts = int(time.time())
        payload = {
            "iss": self.org_id,
            "sub": self.org_id,
            "nbf": now_ts,
            "iat": now_ts,
            "exp": now_ts + 120  # valid for 2 minutes
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    def request(self, method, path, data=None):
        token = self.generate_jwt(method, path)
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        resp = requests.request(method, url, headers=headers, json=data)
        if resp.status_code not in [200, 201]:
            logger.error("Error %s %s: %s", method, path, resp.text)
        return resp.json()

    def list_accounts(self):
        return self.request("GET", "/platform/v1/wallets")


# --- Example Usage ---
if __name__ == "__main__":
    client = CoinbaseJWTClient()
    accounts = client.list_accounts()
    logger.info("Accounts: %s", accounts)
