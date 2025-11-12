import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self, 
                 base="https://api.coinbase.com", 
                 auth_mode="jwt", 
                 jwt_pem=None, 
                 jwt_kid=None, 
                 jwt_issuer=None, 
                 org_id=None):
        self.base = base
        self.auth_mode = auth_mode
        self.jwt_pem = jwt_pem
        self.jwt_kid = jwt_kid
        self.jwt_issuer = jwt_issuer
        self.org_id = org_id

        if self.auth_mode == "jwt":
            self._load_and_validate_pem()
            logger.info(f"Advanced JWT auth enabled (PEM validated). kid={self.jwt_kid} issuer={self.jwt_issuer}")

        logger.info(f"CoinbaseClient initialized. base={self.base}")

    def _load_and_validate_pem(self):
        if not self.jwt_pem:
            raise ValueError("COINBASE_JWT_PEM is required for JWT auth")
        self._private_key = serialization.load_pem_private_key(
            self.jwt_pem.encode(),
            password=None,
            backend=default_backend()
        )
        logger.debug(f"PEM validation via cryptography succeeded.")

    def _jwt_token(self):
        """Generate a JWT token for advanced API"""
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes expiry
            "iss": self.jwt_issuer,
        }
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers={"kid": self.jwt_kid})
        return token

    def _request(self, method, endpoint, **kwargs):
        """
        Internal request handler. Automatically prepends /v2 for JWT (advanced) mode.
        """
        if self.auth_mode == "jwt":
            # Prepend /v2 if not already present
            if not endpoint.startswith("/v2"):
                endpoint = f"/v2{endpoint}"
            url = f"{self.base}{endpoint}"
        else:
            url = f"{self.base}{endpoint}"

        headers = kwargs.pop("headers", {})
        if self.auth_mode == "jwt":
            headers.update({"Authorization": f"Bearer {self._jwt_token()}"})

        r = requests.request(method, url, headers=headers, **kwargs)
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            raise
        return r.json()

    # === Public API Methods ===

    def get_accounts(self):
        """Fetch account list from Coinbase"""
        return self._request("GET", "/accounts")

    # You can add more methods here, e.g., get_prices(), place_order(), etc.
    # Make sure endpoints for JWT mode start with /v2

# === Example usage ===
if __name__ == "__main__":
    import os

    client = CoinbaseClient(
        base=os.getenv("COINBASE_ADVANCED_BASE", "https://api.coinbase.com"),
        auth_mode=os.getenv("COINBASE_AUTH_MODE", "jwt"),
        jwt_pem=os.getenv("COINBASE_JWT_PEM"),
        jwt_kid=os.getenv("COINBASE_JWT_KID"),
        jwt_issuer=os.getenv("COINBASE_JWT_ISSUER"),
        org_id=os.getenv("COINBASE_ORG_ID")
    )

    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
