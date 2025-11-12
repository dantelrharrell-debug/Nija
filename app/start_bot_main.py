import os
import time
import requests
import jwt
from loguru import logger
import sys

# ----------------------
# Coinbase Client Class
# ----------------------
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

        # Check for missing env vars for advanced auth
        if self.auth_mode == "advanced":
            missing = [v for v in ["COINBASE_KEY_ID","COINBASE_JWT_ISS","COINBASE_JWT_PEM","COINBASE_ORG_ID"] if not os.getenv(v)]
            if missing:
                logger.warning("Advanced auth enabled but missing env vars: %s", missing)
        elif not self.api_key:
            logger.error("No API key found for standard auth!")

        logger.info("CoinbaseClient initialized. base=%s auth_mode=%s", self.base_url, self.auth_mode)

    # Generate JWT for advanced auth
    def _get_jwt(self):
        iat = int(time.time())
        payload = {
            "iss": self.jwt_iss,
            "iat": iat,
            "exp": iat + 60,
            "sub": self.org_id
        }
        token = jwt.encode(payload, self.pem_content, algorithm="ES256", headers={"kid": self.key_id})
        return token

    # Headers for requests
    def _headers(self):
        if self.auth_mode == "advanced":
            token = self._get_jwt()
            return {"Authorization": f"Bearer {token}"}
        elif self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        else:
            return {}

    # Generic request
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

    # Get accounts
    def get_accounts(self):
        data = self._request("GET", "/accounts")
        if data:
            return data.get("data", [])
        return None

# ----------------------
# Main loader
# ----------------------
def main():
    logger.info("Starting Nija loader (robust)...")

    # Diagnostics: check important env vars
    def env_present(name):
        return "<present>" if os.getenv(name) else "<missing>"

    logger.info("ENV CHECK: COINBASE_AUTH_MODE=%s", os.getenv("COINBASE_AUTH_MODE"))
    logger.info("ENV CHECK: COINBASE_BASE=%s", os.getenv("COINBASE_BASE"))
    logger.info("ENV CHECK: COINBASE_KEY_ID=%s", env_present("COINBASE_KEY_ID"))
    logger.info("ENV CHECK: COINBASE_JWT_ISS=%s", env_present("COINBASE_JWT_ISS"))
    logger.info("ENV CHECK: COINBASE_JWT_PEM=%s", env_present("COINBASE_JWT_PEM"))
    logger.info("ENV CHECK: COINBASE_ORG_ID=%s", env_present("COINBASE_ORG_ID"))
    logger.info("ENV CHECK: COINBASE_API_KEY=%s", env_present("COINBASE_API_KEY"))

    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()

        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded! Accounts: %s", repr(accounts)[:400])
        logger.info("Nija loader ready to trade...")

    except Exception:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

# Allow script to run directly
if __name__ == "__main__":
    main()
