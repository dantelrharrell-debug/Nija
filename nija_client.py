# nija_client.py
# Safe Coinbase client for Nija. Prefers JWT (Coinbase Advanced / CDP).
# - If COINBASE_JWT missing but COINBASE_PRIVATE_KEY_PATH is set to a PEM, it attempts to generate a short-lived JWT automatically.
# - Will not crash the container on auth/network failures.
# - Provides verbose, actionable logs for fixing permissions/credentials.
#
# Paste this file over /app/nija_client.py and redeploy.

import os
import time
import json
import requests
from loguru import logger
from typing import List, Dict, Optional

# Optional JWT generation
try:
    import jwt as pyjwt  # pyjwt library
    JWT_LIB_AVAILABLE = True
except Exception:
    JWT_LIB_AVAILABLE = False

# Configuration / env names
DEFAULT_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
JWT_ENV = "COINBASE_JWT"
API_KEY_ENV = "COINBASE_API_KEY"
API_SECRET_ENV = "COINBASE_API_SECRET"
API_PASSPHRASE_ENV = "COINBASE_API_PASSPHRASE"
ORG_ENV = "COINBASE_ORG_ID"
PRIVATE_KEY_PATH_ENV = "COINBASE_PRIVATE_KEY_PATH"  # path to PEM for service key -> generate JWT
JWT_ISSUER = os.getenv("COINBASE_JWT_ISSUER", "coinbase")  # informational; not required

# Candidate endpoints (try in sequence)
CANDIDATE_ENDPOINTS = [
    "/platform/v2/evm/accounts",
    "/v2/accounts",
    "/v2/wallet/accounts",
]

# Default JWT lifetime for generated tokens (seconds)
GENERATED_JWT_LIFETIME = 600  # 10 minutes


class CoinbaseClient:
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

        # Basic credential check for logs (do not raise)
        if not (self.jwt or (self.api_key and self.api_secret)):
            logger.error(
                "No usable Coinbase credentials found. Set either COINBASE_JWT (preferred) OR COINBASE_API_KEY and COINBASE_API_SECRET.\n"
                "If using Coinbase Advanced, create a Service Key, download PEM, set COINBASE_PRIVATE_KEY_PATH and COINBASE_ORG_ID, or set COINBASE_JWT directly."
            )
        else:
            logger.success("Found at least one authentication method (JWT or API key/secret).")

        # Attempt to fetch accounts on init (best-effort); will not raise to crash container.
        try:
            accounts = self.fetch_accounts()
            if accounts:
                logger.success(f"Fetched {len(accounts)} account(s).")
            else:
                logger.warning("No accounts returned (empty list). If you expect accounts, check key permissions and COINBASE_API_BASE.")
        except Exception as e:
            logger.exception(f"Unexpected error in fetch_accounts: {e}")

    # Helper: generate simple JWT from PEM if pyjwt available
    def _generate_jwt_if_possible(self) -> Optional[str]:
        """
        Generates a short-lived JWT using the PEM at COINBASE_PRIVATE_KEY_PATH.
        This is intended for Coinbase Advanced Service Keys (PEM-based).
        Non-fatal: returns None on any failure.
        """
        if not JWT_LIB_AVAILABLE:
            logger.warning("pyjwt not installed -> cannot auto-generate a JWT. Install pyjwt (pip install pyjwt) or provide COINBASE_JWT env.")
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

        # Build JWT claims recommended for Coinbase CDP service key usage.
        now = int(time.time())
        payload = {
            "iss": self.org_id,          # org id or key id depending on their JWT expectations
            "sub": self.org_id,
            "iat": now,
            "exp": now + GENERATED_JWT_LIFETIME,
            "aud": "coinbase",           # typical audience; acceptable for many service tokens
            "nbf": now - 10,
        }

        try:
            token = pyjwt.encode(payload, key_bytes, algorithm="RS256")
            # pyjwt returns str in modern versions; ensure str.
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            logger.info("Successfully generated JWT using PEM (temporary token).")
            return token
        except Exception as e:
            logger.exception(f"Failed to encode JWT with PEM: {e}")
            return None

    # ---- HTTP utils ----
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

    # ---- main: fetch accounts ----
    def fetch_accounts(self) -> List[Dict]:
        """
        Attempts to fetch accounts using JWT (preferred) or logs guidance for API key path.
        Returns list of account dicts or empty list. This method is safe and non-raising.
        """
        # Preferred: JWT
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
                        return accounts
                    except Exception as e:
                        logger.exception(f"JSON parsing error from {url}: {e}")
                        return []
                elif resp.status_code in (401, 403):
                    logger.error(f"Authentication/permission error when hitting {url}: {resp.status_code} {resp.reason}")
                    logger.debug(f"Response body (truncated): {self._safe_text(resp)[:1000]}")
                    logger.warning(
                        "401/403 with JWT: verify the JWT was generated for the correct organization, check service-key permissions, "
                        "and ensure COINBASE_API_BASE matches your Coinbase environment (e.g., api.cdp.coinbase.com)."
                    )
                    # continue to next candidate
                else:
                    logger.warning(f"Endpoint {url} returned {resp.status_code} {resp.reason} — trying next.")
            logger.error("All candidate endpoints tried with JWT; none succeeded. Check COINBASE_JWT, COINBASE_ORG_ID, and permissions.")
            return []

        # If no JWT, but API key/secret present -> give guidance (do not attempt fragile HMAC signing automatically)
        if self.api_key and self.api_secret:
            logger.warning(
                "No JWT present but API key/secret found. This client does not auto-sign HMAC by default (to avoid mismatched signing implementations). "
                "Recommended options:\n"
                "  1) Create a Service Key (PEM) in Coinbase Advanced and set COINBASE_PRIVATE_KEY_PATH and COINBASE_ORG_ID (preferred). This client can auto-generate JWTs.\n"
                "  2) If you must use HMAC, ensure the API key has 'accounts.read' permission and the runtime implements the matching HMAC signing flavor for your API type. "
                "If you want, I can provide a minimal HMAC signing snippet for either Retail API (CB-ACCESS-SIGN style) or Advanced HMAC—tell me which key type you created."
            )
            return []

        # No credentials
        logger.error("No Coinbase credentials found (no JWT, no API key/secret). Returning empty list.")
        return []


# If run as main, provide diagnostic output
if __name__ == "__main__":
    logger.info("nija_client.py diagnostic run")
    client = CoinbaseClient()
    logger.info("Diagnostic complete.")
