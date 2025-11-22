# nija_client.py
"""
Robust Coinbase client shim for the NIJA bot.

Goals:
- Avoid crashing on import or missing dependencies (PyJWT, cryptography, loguru).
- Provide safe get_accounts()/fetch_accounts() methods other code expects.
- Attempt to use JWT (ES256) when a PEM or private key path + org id are present and PyJWT[crypto] is installed.
- If JWT generation fails (missing crypto libs, bad key), continue safely and return empty accounts list
  (so the rest of the app can run in DRY_RUN / sandbox / diagnostics mode and not crash).
- Log actionable messages explaining what to set (env vars or requirements).
"""

from __future__ import annotations
import os
import time
import json
from typing import List, Dict, Optional

# Use requests for HTTP; if missing, gracefully degrade to not raising at import.
try:
    import requests
except Exception:
    requests = None  # type: ignore

# Prefer loguru if available, otherwise fallback to standard logging
try:
    from loguru import logger
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("nija_client")  # type: ignore

# Try to import PyJWT; if not present, we will not try to generate ES256 tokens
try:
    import jwt  # PyJWT
except Exception:
    jwt = None  # type: ignore

# For cryptographic operations we rely on cryptography (used by PyJWT[crypto]).
# We'll detect absence and handle it gracefully when attempting to sign.
_CRYPTO_AVAILABLE = False
if jwt is not None:
    try:
        # If PyJWT[crypto] installed, ES algorithms should be available; test by checking algorithm registry
        # This is a non-exceptional check — we'll handle actual NotImplementedError when encoding.
        _ = getattr(jwt, "encode", None)
        _CRYPTO_AVAILABLE = True
    except Exception:
        _CRYPTO_AVAILABLE = False

class CoinbaseClient:
    """
    Safe wrapper to interact with Coinbase / Coinbase Advanced.

    Behavior:
    - Initialization never raises for missing libs; logs warnings instead.
    - generate_jwt() will attempt to create an ES256 JWT if private key contents/path + org id exist.
    - get_accounts() returns list (possibly empty) and never raises to top-level. It logs errors.
    """

    def __init__(self, advanced: bool = True):
        self.advanced = bool(advanced)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # retail
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com" if self.advanced else "https://api.coinbase.com")
        # Preferred: service key PEM content or path + org id for Coinbase Advanced
        self.private_key_path = os.getenv("COINBASE_PRIVATE_KEY_PATH")  # path to PEM file
        # Or raw PEM content (useful in container env var)
        self.private_key_pem = os.getenv("COINBASE_PEM_CONTENT")
        self.org_id = os.getenv("COINBASE_ORG_ID")
        # Derived
        self.jwt_token: Optional[str] = None
        self.jwt_expiry: float = 0.0

        logger.info("nija_client startup: loading Coinbase auth config")
        logger.info(f" - base={self.base_url}")
        logger.info(f" - jwt_set={'yes' if (self.private_key_pem or self.private_key_path) else 'no'}")
        logger.info(f" - api_key_set={'yes' if self.api_key else 'no'}")
        logger.info(f" - api_secret_set={'yes' if self.api_secret else 'no'}")
        logger.info(f" - api_passphrase_set={'yes' if self.passphrase else 'no'}")
        logger.info(f" - org_id_set={'yes' if self.org_id else 'no'}")
        logger.info(f" - private_key_path={'set' if self.private_key_path else 'not set'}")

        # Do not auto-generate JWT here if dependencies are missing; generate lazily
        if jwt is None:
            logger.warning("PyJWT not installed. JWT-based auth will be unavailable until you install PyJWT[crypto].")
        elif not _CRYPTO_AVAILABLE:
            logger.warning("PyJWT imported but crypto backend may not be available. Install PyJWT[crypto] and cryptography.")

        # quick sanity: if nothing present, log a clear actionable message
        if not (self.private_key_pem or self.private_key_path or (self.api_key and self.api_secret)):
            logger.warning(
                "No Coinbase authentication method detected. Set COINBASE_PRIVATE_KEY_PATH or COINBASE_PEM_CONTENT "
                "for Advanced service keys (preferred), or COINBASE_API_KEY and COINBASE_API_SECRET for HMAC-style retail keys."
            )

    # ------------------------------
    # Public methods expected by rest of app
    # ------------------------------
    def get_accounts(self) -> List[Dict]:
        """
        Public method other modules call. Returns a list (can be empty).
        Never raises (exceptions are caught and logged).
        """
        try:
            accounts = self.fetch_accounts()
            if accounts is None:
                return []
            return accounts
        except Exception as e:
            logger.exception(f"Unexpected error in get_accounts: {e}")
            return []

    # ------------------------------
    # Internal helpers
    # ------------------------------
    def _read_private_key(self) -> Optional[str]:
        """
        Return PEM content if present (either from env raw content or reading a path).
        """
        if self.private_key_pem:
            logger.debug("Using COINBASE_PEM_CONTENT from environment.")
            return self.private_key_pem
        if self.private_key_path and os.path.exists(self.private_key_path):
            try:
                with open(self.private_key_path, "r", encoding="utf-8") as fh:
                    pem = fh.read()
                    logger.debug("Loaded private key from COINBASE_PRIVATE_KEY_PATH.")
                    return pem
            except Exception as e:
                logger.warning(f"Failed to read private key path {self.private_key_path}: {e}")
                return None
        return None

    def generate_jwt(self, lifetime_seconds: int = 300) -> Optional[str]:
        """
        Try to generate ES256 JWT for Coinbase Advanced service key auth.
        Returns token string or None on failure.
        This function is safe and will log any missing dependencies instead of raising.
        """
        if jwt is None:
            logger.warning("Cannot generate JWT: PyJWT is not installed.")
            return None

        pem = self._read_private_key()
        if not pem:
            logger.debug("No PEM available to sign JWT.")
            return None

        if not self.org_id:
            logger.warning("COINBASE_ORG_ID not set; required for Advanced service key JWTs.")
            return None

        # Avoid regenerating if still valid
        now = int(time.time())
        if self.jwt_token and self.jwt_expiry - 10 > now:
            return self.jwt_token

        # Build JWT claims according to Coinbase Advanced service key expectations
        payload = {
            "iss": self.org_id,
            "iat": now,
            "exp": now + int(lifetime_seconds),
            "sub": self.org_id,
            # optionally add other claims here if required
        }

        try:
            # Prefer ES256 with provided PEM. Note: PyJWT will raise if cryptography backend missing.
            token = jwt.encode(payload, pem, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt_token = token
            self.jwt_expiry = now + int(lifetime_seconds)
            logger.success("Generated ES256 JWT for Coinbase Advanced service key.")
            return token
        except NotImplementedError as nie:
            logger.warning("ES256 signing backend not available. Install PyJWT[crypto] and cryptography to enable ES256 signing.")
            logger.debug(f"NotImplementedError during JWT encode: {nie}")
            return None
        except Exception as e:
            logger.exception(f"Failed to generate JWT: {e}")
            return None

    def _default_headers(self) -> Dict[str, str]:
        """
        Build default headers for requests. If JWT available will set Authorization Bearer.
        """
        headers = {"Content-Type": "application/json", "User-Agent": "NIJA-Client/1"}
        token = None
        try:
            token = self.generate_jwt()
        except Exception:
            token = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # If JWT not available and retail API key exists, other parts of the code can implement HMAC style headers.
        return headers

    def fetch_accounts(self) -> Optional[List[Dict]]:
        """
        Attempt to fetch accounts from Coinbase / Advanced endpoints.
        This function tries a few candidate endpoints used historically by different Coinbase APIs.
        It will not raise; it returns [] or None on failure, and logs the root cause.

        NOTE: If your code expects live account data to exist, ensure:
          - For Coinbase Advanced service key: COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH and COINBASE_ORG_ID set, and PyJWT[crypto] + cryptography installed.
          - For legacy Retail HMAC keys: COINBASE_API_KEY + COINBASE_API_SECRET and the matching HMAC-signing implementation must be used.
        """
        if requests is None:
            logger.warning("requests library is not installed. Cannot fetch accounts. Add 'requests' to requirements.")
            return None

        # Candidate endpoints: try a few known paths in order.
        candidate_paths = [
            "/platform/v2/evm/accounts",  # Coinbase CDP/EVM style (Advanced)
            "/v2/accounts",               # Retail/API v2
            "/accounts",                  # other variants
        ]

        headers = self._default_headers()

        # If no auth headers present (i.e., no JWT), log guidance and return empty list (do not crash).
        if "Authorization" not in headers:
            logger.warning(
                "No Authorization header set (no JWT). "
                "If you expected accounts, either provide a service key (COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH + COINBASE_ORG_ID) "
                "or implement HMAC signing for COINBASE_API_KEY/COINBASE_API_SECRET. Returning empty list to avoid crash."
            )
            return []

        for path in candidate_paths:
            url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
            try:
                logger.info(f"Trying Coinbase accounts endpoint: {url}")
                resp = requests.get(url, headers=headers, timeout=10)
                # Successful if 200 and JSON accounts
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        # Heuristics: support different shapes
                        if isinstance(data, dict) and "data" in data:
                            accounts = data["data"]
                        elif isinstance(data, dict) and "accounts" in data:
                            accounts = data["accounts"]
                        else:
                            accounts = data
                        logger.success(f"Fetched accounts from {url} (count={len(accounts) if accounts else 0})")
                        return accounts if isinstance(accounts, list) else [accounts]
                    except Exception:
                        logger.exception(f"Failed to parse JSON accounts from {url}: {resp.text[:300]}")
                        return None
                elif resp.status_code in (401, 403):
                    logger.warning(f"Authentication/permission error when fetching accounts from {url}: {resp.status_code} {resp.reason}")
                    # Try next candidate; don't raise
                    continue
                elif resp.status_code == 404:
                    logger.debug(f"Endpoint not found (404) at {url}. Trying other candidate endpoints.")
                    continue
                else:
                    logger.warning(f"Unexpected status code {resp.status_code} from {url}: {resp.text[:300]}")
                    continue
            except Exception as e:
                logger.warning(f"Network/Request exception while fetching accounts from {url}: {e}")
                # Try next
                continue

        logger.error("Failed to fetch Coinbase accounts. Tried candidate endpoints and none returned a successful response. "
                     "Check COINBASE_API_BASE, API keys, and that the API key has permissions to list accounts.")
        # return empty list so caller can continue safely
        return []

# End of nija_client.py
