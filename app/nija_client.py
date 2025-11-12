# app/nija_client.py
import os
import time
import requests
import jwt
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        # Base API URL
        self.base_url = os.getenv("COINBASE_BASE", "https://api.coinbase.com/v2")

        # Auth mode: 'advanced' or something else
        self.auth_mode = os.getenv("COINBASE_AUTH_MODE", "advanced").lower()

        # Standard key auth (not used for advanced)
        self.api_key = os.getenv("COINBASE_API_KEY")

        # Advanced (JWT) auth pieces - coerce to strings and strip whitespace
        raw_key_id = os.getenv("COINBASE_KEY_ID")
        self.key_id = str(raw_key_id).strip() if raw_key_id is not None else None

        self.jwt_iss = os.getenv("COINBASE_JWT_ISS")
        # store raw PEM exactly as provided (preserve newlines)
        self.pem_content = os.getenv("COINBASE_JWT_PEM")
        self.org_id = os.getenv("COINBASE_ORG_ID")

        # Basic checks & diagnostics
        if self.auth_mode == "advanced":
            missing = []
            if not self.key_id:
                missing.append("COINBASE_KEY_ID")
            if not self.jwt_iss:
                missing.append("COINBASE_JWT_ISS")
            if not self.pem_content:
                missing.append("COINBASE_JWT_PEM")
            if not self.org_id:
                missing.append("COINBASE_ORG_ID")

            if missing:
                logger.warning(
                    "Advanced auth enabled but missing env vars: %s. "
                    "Key ID must be a simple string (e.g. 'd3c4f66b-...').",
                    missing
                )
        else:
            if not self.api_key:
                logger.warning("Standard API auth selected but COINBASE_API_KEY is missing.")

        logger.info("CoinbaseClient initialized. base=%s auth_mode=%s", self.base_url, self.auth_mode)

    def _get_jwt(self):
        """Generate JWT for Advanced Auth — safe guards included."""
        # confirm required pieces
        if not (self.key_id and self.pem_content and self.jwt_iss and self.org_id):
            logger.error("Cannot build JWT: missing key_id/pem/jwt_iss/org_id")
            return None

        try:
            iat = int(time.time())
            payload = {
                "iss": self.jwt_iss,
                "iat": iat,
                "exp": iat + 60,  # short-lived
                "sub": self.org_id,
            }
            # Build headers only if key_id is a valid non-empty string
            headers = {}
            if isinstance(self.key_id, str) and self.key_id:
                headers["kid"] = self.key_id
            else:
                logger.error("Invalid COINBASE_KEY_ID: must be a non-empty string.")
                return None

            token = jwt.encode(payload, self.pem_content, algorithm="ES256", headers=headers)
            # PyJWT returns str in v2+, but ensure string
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            return token
        except Exception as e:
            logger.exception("Failed to generate JWT: %s", e)
            return None

    def _headers(self):
        if self.auth_mode == "advanced":
            token = self._get_jwt()
            if not token:
                logger.error("Advanced auth enabled but JWT generation failed.")
                return {}
            return {"Authorization": f"Bearer {token}"}
        elif self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        else:
            logger.error("No authentication method available: set COINBASE_API_KEY or advanced vars.")
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
        data = self._request("GET", "/accounts")
        if data:
            return data.get("data", [])
        return None
