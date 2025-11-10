# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseClient:
    """
    Simple Coinbase Client for Nija Bot.
    Handles JWT auth and fetching account balances.
    """

    def __init__(self, base_url=None, pem_content=None, issuer=None):
        self.base_url = base_url or "https://api.cdp.coinbase.com"
        self.pem_content = pem_content or os.getenv("COINBASE_PEM_CONTENT")
        self.issuer = issuer or os.getenv("COINBASE_ISS")
        self.jwt_token = None

        if not self.pem_content:
            raise ValueError("PEM content required for CoinbaseClient")

        self._generate_jwt()
        logger.info(f"NIJA-CLIENT-READY: base={self.base_url} jwt_set={self.jwt_token is not None}")

    def _generate_jwt(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "iss": self.issuer
        }
        try:
            self.jwt_token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            self.jwt_token = None

    def get_accounts(self):
        """
        Fetch accounts from Coinbase Advanced API.
        """
        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        try:
            response = requests.get(f"{self.base_url}/api/v3/brokerage/accounts", headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Advanced API returned {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return None

    def get_classic_accounts(self):
        """
        Fetch accounts from Classic Coinbase API as fallback.
        """
        api_key = os.getenv("COINBASE_API_KEY")
        api_secret = os.getenv("COINBASE_API_SECRET")
        if not api_key or not api_secret:
            logger.warning("Classic API credentials missing")
            return None

        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            response = requests.get("https://api.coinbase.com/v2/accounts", headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Classic API returned {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error fetching classic accounts: {e}")
            return None
