# /app/nija_client.py
"""
Nija Coinbase client (drop-in file)

Features:
- Provides CoinbaseClient with fetch_accounts(), get_accounts(), list_accounts().
- Uses JWT if available, can auto-generate JWT from PEM (if pyjwt installed).
- Falls back to CB-ACCESS-SIGN HMAC style signing using COINBASE_API_KEY and COINBASE_API_SECRET as a best-effort.
- Tries multiple endpoints commonly used by Coinbase / Coinbase Advanced / CDP.
- Conservative: does not throw on import; logs issues instead so container won't crash.
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
from typing import List, Dict, Optional
from loguru import logger

# Optional PyJWT support (for PEM -> JWT generation)
try:
    import jwt as pyjwt  # PyJWT
    PYJWT_AVAILABLE = True
except Exception:
    PYJWT_AVAILABLE = False

# Config via env
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
COINBASE_JWT = os.getenv("COINBASE_JWT")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PRIVATE_KEY_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH")

# Candidate account endpoints to try (order prioritized)
CANDIDATE_ENDPOINTS = [
    "/platform/v2/evm/accounts",   # Coinbase CDP/EVM (Advanced)
    "/platform/v2/accounts",       # alternative CDP
    "/v2/accounts",                # retail/legacy
    "/v2/wallet/accounts",
]

# Default JWT lifetime when auto-generating
AUTO_JWT_LIFETIME = 600  # 10 minutes


class CoinbaseClient:
    """
    Coinbase client for Nija. Exposes:
      - fetch_accounts()
      - get_accounts()
      - list_accounts()
    Behavior:
      1. Use COINBASE_JWT if set.
      2. Else try to auto-generate JWT from PEM if COINBASE_PRIVATE_KEY_PATH + COINBASE_ORG_ID set and PyJWT available.
      3. Else try HMAC-style signing with API_KEY + API_SECRET (CB-ACCESS-SIGN style) as best-effort.
    This class aims to be defensive and not crash container startup.
    """

    def __init__(self, advanced: bool = True, base: Optional[str] = None):
        self.advanced = advanced
        self.base = base or COINBASE_API_BASE
        # read envs at init-time (fresh)
        self.jwt = os.getenv("COINBASE_JWT") or COINBASE_JWT
        self.api_key = os.getenv("COINBASE_API_KEY") or COINBASE_API_KEY
        self.api_secret = os.getenv("COINBASE_API_SECRET") or COINBASE_API_SECRET
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE") or COINBASE_API_PASSPHRASE
        self.org_id = os.getenv("COINBASE_ORG_ID") or COINBASE_ORG_ID
        self.private_key_path = os.getenv("COINBASE_PRIVATE_KEY_PATH") or COINBASE_PRIVATE_KEY_PATH

        logger.info("nija_client startup: loading Coinbase auth config")
        logger.info(f" - base={self.base}")
        logger.info(f" - jwt_set={'yes' if self.jwt else 'no'}")
        logger.info(f" - api_key_set={'yes' if self.api_key else 'no'}")
        logger.info(f" - api_secret_set={'yes' if self.api_secret else 'no'}")
        logger.info(f" - api_passphrase_set={'yes' if self.api_passphrase else 'no'}")
        logger.info(f" - org_id_set={'yes' if self.org_id else 'no'}")
        logger.info(f" - private_key_path={'set' if self.private_key_path else 'not set'}")
        logger.info(f"Advanced mode: {self.advanced}")

        # If no JWT but PEM available, attempt to generate a short-lived JWT (non-fatal)
        if not self.jwt and self.private_key_path and self.org_id:
            if PYJWT_AVAILABLE:
                try:
                    token = self._generate_jwt_from_pem()
                    if token:
                        self.jwt = token
                        logger.success("Auto-generated ephemeral JWT from PEM for this runtime (temporary).")
                    else:
                        logger.warning("JWT auto-generation returned no token.")
                except Exception as e:
                    logger.warning(f"JWT auto-generation failed: {e}")
            else:
                logger.warning("PyJWT not installed: cannot auto-generate JWT from PEM. Install PyJWT or set COINBASE_JWT env.")

        if not (self.jwt or (self.api_key and self.api_secret)):
            logger.error(
                "No usable Coinbase credentials found. Either set COINBASE_JWT (recommended) or COINBASE_API_KEY and COINBASE_API_SECRET.\n"
                "If using Coinbase Advanced, create a Service Key (PEM) in Coinbase, set COINBASE_PRIVATE_KEY_PATH and COINBASE_ORG_ID, or set COINBASE_JWT."
            )
        else:
            logger.success("Found at least one authentication method (JWT or API key/secret).")

        # run a safe diagnostic fetch so logs provide early info (non-fatal)
        try:
            accounts = self.fetch_accounts()
            if accounts:
                logger.success(f"Initialization: found {len(accounts)} account(s).")
            else:
                logger.warning("Initialization: no accounts returned (may be permission issue or wrong endpoint).")
        except Exception as e:
            logger.exception(f"Initialization account fetch raised unexpected exception: {e}")

    # ---------------- JWT from PEM ----------------
    def _generate_jwt_from_pem(self) -> Optional[str]:
        """Generate a short-lived JWT from PEM file using PyJWT (RS256)."""
        if not PYJWT_AVAILABLE:
            return None
        if not os.path.isfile(self.private_key_path):
            logger.warning(f"PEM not found at {self.private_key_path}")
            return None
        try:
            with open(self.private_key_path, "rb") as f:
                key_bytes = f.read()
        except Exception as e:
            logger.warning(f"Failed to read PEM: {e}")
            return None

        now = int(time.time())
        payload = {
            "iss": self.org_id,
            "sub": self.org_id,
            "iat": now,
            "exp": now + AUTO_JWT_LIFETIME,
            "aud": "coinbase",
        }
        try:
            token = pyjwt.encode(payload, key_bytes, algorithm="RS256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            return token
        except Exception as e:
            logger.warning(f"Failed to encode JWT with PEM: {e}")
            return None

    # ---------------- Helpers ----------------
    def _join(self, base: str, path: str) -> str:
        if base.endswith("/") and path.startswith("/"):
            return base[:-1] + path
        if not base.endswith("/") and not path.startswith("/"):
            return base + "/" + path
        return base + path

    def _bearer_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "nija-client/1.0",
        }

    # Basic CB-ACCESS-SIGN style HMAC for GET requests (best-effort).
    # This mirrors Coinbase Pro / CB-ACCESS-SIGN semantics: timestamp + method + path + body, HMAC-SHA256, base64.
    # NOTE: Depending on which API/region/key style you created, HMAC signing flavor may differ. This is a best-effort fallback.
    def _hmac_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        if not (self.api_key and self.api_secret):
            raise RuntimeError("API key/secret not set for HMAC signing")
        timestamp = str(int(time.time()))
        request_path = path if path.startswith("/") else "/" + path
        prehash = timestamp + method.upper() + request_path + (body or "")
        try:
            secret_bytes = base64.b64decode(self.api_secret)
        except Exception:
            # if API_SECRET is raw hex or raw string, fallback to using as bytes directly
            secret_bytes = (self.api_secret or "").encode("utf-8")
        signature = hmac.new(secret_bytes, prehash.encode("utf-8"), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Accept": "application/json",
            "User-Agent": "nija-client/1.0",
        }
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase
        return headers

    def _try_get(self, url: str, headers: Dict[str, str], timeout: int = 8) -> Optional[requests.Response]:
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network/Request exception for {url}: {e}")
            return None

    def _extract_accounts(self, payload) -> List[Dict]:
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                return payload["data"]
            if "accounts" in payload and isinstance(payload["accounts"], list):
                return payload["accounts"]
            # sometimes returns {"result": [...]} or others
            for key in ("result", "accounts", "data"):
                if key in payload and isinstance(payload[key], list):
                    return payload[key]
        if isinstance(payload, list):
            return payload
        return []

    # ---------------- Main account fetching ----------------
    def fetch_accounts(self) -> List[Dict]:
        """
        Attempt to fetch accounts via multiple strategies:
         - JWT (preferred)
         - HMAC with API key/secret (best-effort)
        Returns list of accounts (possibly empty). Does not raise on auth/network issues.
        """
        # 1) Try JWT if present
        if self.jwt:
            headers = self._bearer_headers(self.jwt)
            logger.info("Trying to fetch accounts using JWT; iterating candidate endpoints.")
            for path in CANDIDATE_ENDPOINTS:
                url = self._join(self.base, path)
                logger.info(f"Attempting JWT GET {url}")
                resp = self._try_get(url, headers)
                if resp is None:
                    continue
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                        accounts = self._extract_accounts(payload)
                        logger.success(f"JWT accounts fetch successful at {url} (found {len(accounts)}).")
                        return accounts
                    except Exception as e:
                        logger.warning(f"JSON parse error for {url}: {e}")
                        return []
                elif resp.status_code in (401, 403):
                    logger.error(f"JWT auth error at {url}: {resp.status_code} {resp.reason}")
                    logger.debug(f"Response body truncated: {resp.text[:1000]}")
                    # keep trying other candidate endpoints
                else:
                    logger.warning(f"Endpoint {url} returned {resp.status_code} {resp.reason}; trying next candidate.")
            logger.error("JWT present but all candidate endpoints failed. Check JWT, COINBASE_ORG_ID, and COINBASE_API_BASE.")
            return []

        # 2) Try HMAC signing with API key if JWT not available
        if self.api_key and self.api_secret:
            logger.info("No JWT — trying HMAC signed requests using COINBASE_API_KEY/SECRET (best-effort).")
            for path in CANDIDATE_ENDPOINTS:
                url = self._join(self.base, path)
                # we sign using request path portion (path) not full URL
                try:
                    request_path = path if path.startswith("/") else "/" + path
                    headers = self._hmac_headers("GET", request_path, "")
                except Exception as e:
                    logger.warning(f"Failed to build HMAC headers: {e}")
                    continue
                logger.info(f"Attempting HMAC-signed GET {url}")
                resp = self._try_get(url, headers)
                if resp is None:
                    continue
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                        accounts = self._extract_accounts(payload)
                        logger.success(f"HMAC accounts fetch successful at {url} (found {len(accounts)}).")
                        return accounts
                    except Exception as e:
                        logger.warning(f"JSON parse error at {url}: {e}")
                        return []
                elif resp.status_code in (401, 403):
                    logger.error(f"HMAC auth error at {url}: {resp.status_code} {resp.reason}")
                    logger.debug(f"Response body truncated: {resp.text[:1000]}")
                    # permission or wrong signature; try next endpoint
                else:
                    logger.warning(f"HMAC endpoint {url} returned {resp.status_code} {resp.reason}; trying next.")
            logger.error("HMAC path attempted but all endpoints failed. Verify API key permissions (accounts.read) and signing flavor.")
            return []

        # 3) No method available
        logger.error("No authentication method available to fetch accounts (no JWT, no API key/secret).")
        return []

    # Compatibility aliases (other modules may call any of these names)
    def get_accounts(self) -> List[Dict]:
        return self.fetch_accounts()

    def list_accounts(self) -> List[Dict]:
        return self.fetch_accounts()


# If run directly, print diagnostics
if __name__ == "__main__":
    logger.info("nija_client diagnostic run")
    client = CoinbaseClient()
    accs = client.get_accounts()
    logger.info(f"Diagnostic: found {len(accs)} accounts.")
