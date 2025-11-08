# nija_client.py
# Safe Coinbase client for Nija. Prefers JWT (Coinbase Advanced / CDP).
# - Provides fetch_accounts(), get_accounts(), and list_accounts() for compatibility.
# - If COINBASE_JWT missing but COINBASE_PRIVATE_KEY_PATH is set to a PEM, attempts to generate a short-lived JWT automatically.
# - Will not crash the container on auth/network failures; logs actionable diagnostics.
# - Minimal external deps: requests and loguru. pyjwt optional (for auto-JWT generation).

import os
import time
import json
import requests
from loguru import logger
from typing import List, Dict, Optional

# Optional JWT generation
try:
    import jwt as pyjwt  # PyJWT
    JWT_LIB_AVAILABLE = True
except Exception:
    JWT_LIB_AVAILABLE = False

# Environment variables
DEFAULT_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
JWT_ENV = "COINBASE_JWT"
API_KEY_ENV = "COINBASE_API_KEY"
API_SECRET_ENV = "COINBASE_API_SECRET"
API_PASSPHRASE_ENV = "COINBASE_API_PASSPHRASE"
ORG_ENV = "COINBASE_ORG_ID"
PRIVATE_KEY_PATH_ENV = "COINBASE_PRIVATE_KEY_PATH"  # path to PEM for service key -> generate JWT

# Candidate endpoints to try (order matters: try CDP-style first)
CANDIDATE_ENDPOINTS = [
    "/platform/v2/evm/accounts",
    "/v2/accounts",
    "/v2/wallet/accounts",
]

# Default JWT lifetime for generated tokens (seconds)
GENERATED_JWT_LIFETIME = 600  # 10 minutes


class CoinbaseClient:
    """
    Coinbase client with safe, non-crashing behavior.
    Provides multiple method names for compatibility: fetch_accounts(), get_accounts(), list_accounts().
    """

    def __init__(self, advanced: bool = True, base: Optional[str] = None):
        self.advanced = advanced
        self.base = base or DEFAULT_BASE
        self.jwt = os.getenv(JWT_ENV)
        self.api_key = os.getenv(API_KEY_ENV)
        self.api_secret = os.getenv(API_SECRET_ENV)
        self.api_passphrase = os.getenv(API_PASSPHRASE_ENV)
        self.org_id = os.getenv(ORG_ENV)
        self.private_key_path = os.getenv(PRIVATE_KEY_PATH_ENV)

        logger.info("nija_client startup: loading Coinbase auth config")
        logger.info(f" - base={self.base}")
        logger.info(f" - jwt_set={'yes' if self.jwt else 'no'}")
        logger.info(f" - api_key_set={'yes' if self.api_key else 'no'}")
        logger.info(f" - api_secret_set={'yes' if self.api_secret else 'no'}")
        logger.info(f" - api_passphrase_set={'yes' if self.api_passphrase else 'no'}")
        logger.info(f" - org_id_set={'yes' if self.org_id else 'no'}")
        logger.info(f" - private_key_path={'set' if self.private_key_path else 'not set'}")
        logger.info(f"Advanced mode: {self.advanced}")

        # If no JWT but PEM path present -> try generate one (non-fatal).
        if not self.jwt and self.private_key_path:
            logger.info("No COINBASE_JWT found; COINBASE_PRIVATE_KEY_PATH present -> attempting to generate JWT (auto).")
            gen = self._generate_jwt_if_possible()
            if gen:
                self.jwt = gen
                logger.success("Auto-generated COINBASE_JWT and set for this runtime.")
            else:
                logger.warning("Auto-generation of JWT failed or pyjwt not available. Proceeding without JWT.")

        # Log credential summary
        if not (self.jwt or (self.api_key and self.api_secret)):
            logger.error(
                "No usable Coinbase credentials found. Set either COINBASE_JWT (preferred) OR COINBASE_API_KEY and COINBASE_API_SECRET.\n"
                "If using Coinbase Advanced, create a Service Key, download PEM, set COINBASE_PRIVATE_KEY_PATH and COINBASE_ORG_ID, or set COINBASE_JWT directly."
            )
        else:
            logger.success("Found at least one authentication method (JWT or API key/secret).")

        # Best-effort fetch to help surface errors in logs (will not raise)
        try:
            accounts = self.fetch_accounts()
            if accounts:
                logger.success(f"Fetched {len(accounts)} account(s) on initialization.")
            else:
                logger.warning("No accounts returned on initialization. If you expect accounts, check key permissions and COINBASE_API_BASE.")
        except Exception as e:
            logger.exception(f"Unexpected error during initial account fetch: {e}")

    # ----------------- JWT generation helper -----------------
    def _generate_jwt_if_possible(self) -> Optional[str]:
        """
        Generates a short-lived JWT using the PEM at COINBASE_PRIVATE_KEY_PATH.
        Returns token string or None on failure.
        """
        if not JWT_LIB_AVAILABLE:
            logger.warning("pyjwt not installed -> cannot auto-generate a JWT. Install PyJWT or set COINBASE_JWT.")
            return None
        if not self.private_key_path or not os.path.isfile(self.private_key_path):
            logger.warning("COINBASE_PRIVATE_KEY_PATH not set or PEM file not found in container.")
            return None
        if not self.org_id:
            logger.warning("COINBASE_ORG_ID not set - required to generate service-key JWT for Advanced API.")
            return None

        try:
            with open(self.private_key_path, "rb") as f:
                key_bytes = f.read()
        except Exception as e:
            logger.exception(f"Failed to read PEM at {self.private_key_path}: {e}")
            return None

        now = int(time.time())
        payload = {
            "iss": self.org_id,
            "sub": self.org_id,
            "iat": now,
            "exp": now + GENERATED_JWT_LIFETIME,
            "aud": "coinbase",
            "nbf": now - 10,
        }

        try:
            token = pyjwt.encode(payload, key_bytes, algorithm="RS256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            logger.info("Successfully generated JWT using PEM (temporary token).")
            return token
        except Exception as e:
            logger.exception(f"Failed to encode JWT with PEM: {e}")
            return None

    # ----------------- HTTP helpers -----------------
    def _bearer_headers(self, jwt_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nija-client/1.0",
        }

    def _try_get(self, url: str, headers: Dict[str, str], timeout: int = 8) -> Optional[requests.Response]:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            return resp
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network/Request exception for {url}: {e}")
            return None

    def _join(self, base: str, path: str) -> str:
        if base.endswith("/") and path.startswith("/"):
            return base[:-1] + path
        if not base.endswith("/") and not path.startswith("/"):
            return base + "/" + path
        return base + path

    def _safe_text(self, resp: requests.Response) -> str:
        try:
            return resp.text
        except Exception:
            return "<unreadable response>"

    def _extract_accounts_from_payload(self, payload: Dict) -> List[Dict]:
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                return payload["data"]
            if "accounts" in payload and isinstance(payload["accounts"], list):
                return payload["accounts"]
        if isinstance(payload, list):
            return payload
        return []

    # ----------------- Account fetching (main) -----------------
    def fetch_accounts(self) -> List[Dict]:
        """
        Attempt to fetch accounts using JWT (preferred).
        Returns a list (possibly empty). Non-raising on auth/network errors.
        """
        if self.jwt:
            headers = self._bearer_headers(self.jwt)
            logger.info("Using JWT to fetch accounts; trying candidate endpoints.")
            for path in CANDIDATE_ENDPOINTS:
                url = self._join(self.base, path)
                logger.info(f"Trying Coinbase accounts endpoint: {url}")
                resp = self._try_get(url, headers)
                if resp is None:
                    continue
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                        accounts = self._extract_accounts_from_payload(payload)
                        logger.info(f"Accounts endpoint successful: {url}")
                        return accounts
                    except Exception as e:
                        logger.exception(f"JSON parsing error from {url}: {e}")
                        return []
                elif resp.status_code in (401, 403):
                    logger.error(f"Authentication/permission error when hitting {url}: {resp.status_code} {resp.reason}")
                    logger.debug(f"Response body (truncated): {self._safe_text(resp)[:1200]}")
                    logger.warning(
                        "401/403 with JWT: verify the JWT was generated for the correct organization, check service-key permissions, "
                        "and ensure COINBASE_API_BASE matches your Coinbase environment (e.g., api.cdp.coinbase.com)."
                    )
                    # Continue trying other endpoints to be thorough
                else:
                    logger.warning(f"Endpoint {url} returned {resp.status_code} {resp.reason} — trying next.")
            logger.error("All candidate endpoints tried with JWT; none succeeded. Check COINBASE_JWT, COINBASE_ORG_ID, and permissions.")
            return []

        # If no JWT present but API key/secret exist, provide guidance and do not auto-sign by default.
        if self.api_key and self.api_secret:
            logger.warning(
                "No JWT present but API key/secret found. This client does not auto-sign HMAC by default (to avoid mismatched signing implementations).\n"
                "Recommended options:\n"
                "  1) Create a Service Key (PEM) in Coinbase Advanced and set COINBASE_PRIVATE_KEY_PATH and COINBASE_ORG_ID (preferred). This client can auto-generate JWTs.\n"
                "  2) If you must use HMAC, ensure the API key has 'accounts.read' permission and implement matching HMAC signing. If you want, I can provide a minimal HMAC signing snippet."
            )
            return []

        logger.error("No Coinbase credentials found (no JWT, no API key/secret). Returning empty list.")
        return []

    # Compatibility aliases expected by other modules:
    def get_accounts(self) -> List[Dict]:
        """Alias for fetch_accounts() — used in other parts of the codebase."""
        return self.fetch_accounts()

    def list_accounts(self) -> List[Dict]:
        """Another alias for fetch_accounts()."""
        return self.fetch_accounts()


# Diagnostic run if invoked directly
if __name__ == "__main__":
    logger.info("nija_client.py diagnostic run")
    client = CoinbaseClient()
    accounts = client.get_accounts()
    logger.info(f"Diagnostic: returned {len(accounts)} accounts.")
