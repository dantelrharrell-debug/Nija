# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseClient:
    """
    Minimal Coinbase Client for Nija Bot.
    Supports ephemeral JWT and basic account/balance placeholders.
    """

    def __init__(self, base=None, jwt_token=None):
        self.base = base or "https://api.cdp.coinbase.com"
        self.jwt = jwt_token
        self.headers = {}
        if self.jwt:
            self.headers["Authorization"] = f"Bearer {self.jwt}"
        logger.info(f"CoinbaseClient initialized: base={self.base}, jwt_set={self.jwt is not None}")

    @staticmethod
    def generate_ephemeral_jwt(pem_content=None, iss=None):
        """
        Generate ephemeral JWT from PEM content (for Advanced API)
        """
        pem_content = pem_content or os.getenv("COINBASE_PEM_CONTENT")
        iss = iss or os.getenv("COINBASE_ISS")
        if not pem_content or not iss:
            raise ValueError("Missing PEM content or ISS for JWT generation")

        payload = {
            "iss": iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + 30,  # 30s expiry
        }
        token = jwt.encode(payload, pem_content, algorithm="ES256")
        return token

    def get_accounts(self):
        """
        Placeholder for fetching accounts.
        Replace with actual API calls when ready.
        """
        logger.info("[CoinbaseClient] get_accounts() called")
        # Example structure
        return [
            {"id": "acct_1", "currency": "USD", "balance": 1000},
            {"id": "acct_2", "currency": "BTC", "balance": 0.05}
        ]

    def get_balance(self):
        """
        Calculate total balance across accounts (placeholder logic)
        """
        accounts = self.get_accounts()
        total_balance = sum(a["balance"] for a in accounts)
        logger.info(f"[CoinbaseClient] Total balance calculated: {total_balance}")
        return total_balance

# Quick test when running directly
if __name__ == "__main__":
    try:
        client = CoinbaseClient(jwt_token="TEST_JWT")
        accounts = client.get_accounts()
        balance = client.get_balance()
        print("CoinbaseClient initialized and test run successful!")
        print("Accounts:", accounts)
        print("Total balance:", balance)
    except Exception as e:
        print("Error testing CoinbaseClient:", e)
