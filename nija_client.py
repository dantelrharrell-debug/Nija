# nija_client.py
import os, time, jwt, requests
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

class CoinbaseClient:
    def __init__(self):
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT", "")
        self.api_key = os.environ.get("COINBASE_API_KEY", "")

        if not all([self.org_id, self.pem_raw, self.api_key]):
            raise ValueError("Missing Coinbase credentials")

        self.pem_fixed = self.pem_raw.replace("\\n", "\n")

        # Determine sub variants
        self.sub_variants = []
        if "organizations/" in self.api_key:
            self.sub_variants.append(self.api_key)
        else:
            self.sub_variants.append(f"organizations/{self.org_id}/apiKeys/{self.api_key}")
            self.sub_variants.append(self.api_key)  # try raw key as fallback

    def generate_jwt(self, sub):
        payload = {"sub": sub, "iat": int(time.time()), "exp": int(time.time()) + 60}
        return jwt.encode(payload, self.pem_fixed, algorithm="ES256")

    def test_auth(self):
        url = "https://api.coinbase.com/v2/accounts"
        for sub in self.sub_variants:
            token = self.generate_jwt(sub)
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(url, headers=headers)
            logger.info(f"Trying sub: {sub}")
            logger.info(f"Status: {r.status_code}")
            if r.status_code == 200:
                logger.success("✅ Auth successful!")
                return r.json()
            else:
                logger.error(f"Response: {r.text}")
        logger.error("All sub variants failed!")
        return None

if __name__ == "__main__":
    client = CoinbaseClient()
    client.test_auth()
