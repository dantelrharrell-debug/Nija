# app/nija_client.py
# Python 3.9+ recommended. Requires: pyjwt, cryptography, requests, loguru

import os
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        # Load env vars
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")

        if not all([self.api_key, self.org_id, self.pem_content]):
            logger.error("Missing Coinbase credentials in environment variables!")
            raise ValueError("Coinbase API key, Org ID, or PEM missing")

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        # Load PEM key
        self._load_pem()

    def _load_pem(self):
        try:
            # Fix PEM formatting if stored with \n instead of newlines
            pem_fixed = self.pem_content.replace("\\n", "\n")
            self.private_key = serialization.load_pem_private_key(
                pem_fixed.encode("utf-8"),
                password=None,
                backend=default_backend()
            )
            logger.info("PEM loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load PEM: {e}")
            raise e

    def _generate_jwt(self):
        iat = int(time.time())
        exp = iat + 300  # JWT valid for 5 minutes
        payload = {
            "iat": iat,
            "exp": exp,
            "sub": self.org_id
        }

        try:
            token = jwt.encode(
                payload,
                self.private_key,
                algorithm="ES256",
                headers={"kid": self.api_key}  # Coinbase API key as KID
            )
            return token
        except Exception as e:
            logger.error(f"JWT generation failed: {e}")
            raise e

    def get_accounts(self):
        token = self._generate_jwt()
        headers = {"Authorization": f"Bearer {token}"}
        url = "https://api.coinbase.com/v2/accounts"
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Coinbase API Error {resp.status_code}: {resp.text}")
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None

# Quick test
if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.get_accounts()
    if accounts:
        logger.info(accounts)
    else:
        logger.warning("No accounts returned. Check credentials.")
