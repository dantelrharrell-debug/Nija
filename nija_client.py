# nija_client.py
import os
import requests
import json
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt
import time

class CoinbaseClient:
    def __init__(self):
        # Load environment variables
        self.auth_mode = os.getenv("COINBASE_AUTH_MODE", "jwt")
        self.base = os.getenv("COINBASE_ADVANCED_BASE")
        self.kid = os.getenv("COINBASE_JWT_KID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER")
        self.pem = os.getenv("COINBASE_JWT_PEM")
        self.org_id = os.getenv("COINBASE_ORG_ID")

        # Validate PEM
        if self.pem:
            self._load_and_validate_pem()
            logger.info(f"Advanced JWT auth enabled (PEM validated). kid={self.kid} issuer={self.issuer}")
        else:
            logger.error("COINBASE_JWT_PEM missing, cannot use JWT auth")
            raise ValueError("COINBASE_JWT_PEM missing")

    def _load_and_validate_pem(self):
        try:
            self.private_key = serialization.load_pem_private_key(
                self.pem.encode(),
                password=None,
                backend=default_backend()
            )
            logger.debug(f"PEM validation via cryptography succeeded.")
        except Exception as e:
            logger.error(f"PEM validation failed: {e}")
            raise e

    def _generate_jwt(self):
        iat = int(time.time())
        exp = iat + 60  # short-lived token
        payload = {
            "iat": iat,
            "exp": exp,
            "iss": self.issuer
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256", headers={"kid": self.kid})
        return token

    def _request(self, method, endpoint, data=None):
        url = f"{self.base}{endpoint}"  # base already includes /v2/organizations/<ORG_ID>
        headers = {}
        if self.auth_mode == "jwt":
            headers["Authorization"] = f"Bearer {self._generate_jwt()}"
            headers["Content-Type"] = "application/json"
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                r = requests.post(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            raise e
        except Exception as e:
            logger.error(f"Request error for {url}: {e}")
            raise e

    # ===========================
    # Public API methods
    # ===========================
    def get_accounts(self):
        return self._request("GET", "/accounts")

    def get_account(self, account_id):
        return self._request("GET", f"/accounts/{account_id}")

    def create_transaction(self, account_id, tx_data):
        return self._request("POST", f"/accounts/{account_id}/transactions", data=tx_data)
