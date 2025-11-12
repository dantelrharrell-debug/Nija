import os
import requests
import time
import jwt
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        # Base API URL
        self.base_url = os.getenv("COINBASE_BASE", "https://api.coinbase.com/v2")
        self.auth_mode = os.getenv("COINBASE_AUTH_MODE", "advanced").lower()
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.key_id = os.getenv("COINBASE_KEY_ID")
        self.jwt_iss = os.getenv("COINBASE_JWT_ISS")
        self.pem_content = os.getenv("COINBASE_JWT_PEM")
        self.org_id = os.getenv("COINBASE_ORG_ID")

        if self.auth_mode != "advanced":
            logger.warning("Using standard API key auth; advanced auth recommended for live trading.")
        else:
            missing = [v for v in ["COINBASE_KEY_ID", "COINBASE_JWT_ISS", "COINBASE_JWT_PEM", "COINBASE_ORG_ID"]
                       if not os.getenv(v)]
            if missing:
                logger.warning("Advanced auth enabled but missing env vars: %s", missing)

        logger.info("CoinbaseClient initialized. base=%s auth_mode=%s", self.base_url, self.auth_mode)

    def _get_jwt(self):
        """Generate JWT for Advanced Auth"""
        iat = int(time.time())
        payload = {
            "iss": self.jwt_iss,
            "iat": iat,
            "exp": iat + 60,  # token valid for 60 seconds
            "sub": self.org_id,
        }
        token = jwt.encode(payload, self.pem_content, algorithm="ES256", headers={"kid": self.key_id})
        return token

    def _headers(self):
        if self.auth_mode == "advanced":
            token = self._get_jwt()
            return {"Authorization": f"Bearer {token}"}
        elif self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        else:
            logger.error("No authentication method available")
            return {}

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        try:
            r = requests.request(method, url, headers=headers, **kwargs)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning("HTTP request failed for %s: %s", url, e)
            return None
        except Exception as e:
            logger.exception("Request error for %s: %s", url, e)
            return None

    def get_accounts(self):
        """Return list of Coinbase accounts"""
        data = self._request("GET", "/accounts")
        if data:
            return data.get("data", [])
        return None
