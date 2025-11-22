# nija_client.py
"""
Robust Coinbase client adapter for NIJA bot.

Design goals:
 - Safe to import: no network calls at import time.
 - Support Coinbase Advanced (JWT with PEM) and Retail (HMAC with API key/secret/passphrase).
 - Provide get_accounts() which other modules expect.
 - Fail loudly only when required credentials are missing, otherwise return empty lists with logs.
 - Gracefully handle missing optional crypto libraries (PyJWT[crypto], cryptography).
"""

from __future__ import annotations
import os
import time
import json
import hmac
import hashlib
from typing import Optional, List, Dict, Any, Tuple
import base64

import requests  # Ensure requests is in requirements.txt
from loguru import logger

# Try to import PyJWT[crypto] and cryptography; if not available, we'll gracefully fallback.
try:
    import jwt  # PyJWT
    _HAS_PYJWT = True
except Exception:
    jwt = None
    _HAS_PYJWT = False

# Try to import cryptography for EC keys (ES256)
try:
    # cryptography is used indirectly by PyJWT for ES256 signing if installed
    import cryptography  # type: ignore
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False

# Default candidate bases / endpoints for Coinbase Advanced and Retail
DEFAULT_BASES = [
    "https://api.cdp.coinbase.com",  # Coinbase Advanced
    "https://api.coinbase.com",       # Coinbase Retail (classic)
]

# Candidate account-listing endpoints for Coinbase Advanced and Retail.
# We'll try these in order, logging what we try.
CANDIDATE_ACCOUNT_ENDPOINTS = [
    "/platform/v2/evm/accounts",     # advanced EVM/accounts
    "/platform/v2/accounts",         # advanced generic accounts
    "/v2/accounts",                  # retail API
    "/accounts",                     # fallback
]


class CoinbaseClient:
    def __init__(self, base: Optional[str] = None, advanced: Optional[bool] = None):
        """
        Initialize a client. This does NOT perform network calls.
        Use get_accounts() to request accounts later.

        Parameters:
         - base: override COINBASE_API_BASE env var
         - advanced: if True forces Advanced mode; if False forces Retail/HMAC;
                     if None, auto-detect from env (presence of PEM/ORG -> Advanced)
        """
        self.api_key = os.getenv("COINBASE_API_KEY") or None
        self.api_secret = os.getenv("COINBASE_API_SECRET") or None
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE") or None
        self.base = base or os.getenv("COINBASE_API_BASE") or DEFAULT_BASES[0]
        # Service key PEM (for Coinbase Advanced) can be provided either via env PEM content
        # or via a file path in COINBASE_PRIVATE_KEY_PATH
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT") or None
        self.private_key_path = os.getenv("COINBASE_PRIVATE_KEY_PATH") or None
        self.org_id = os.getenv("COINBASE_ORG_ID") or None

        # If advanced param explicitly provided, respect it; else detect heuristically
        if advanced is None:
            # prefer advanced if we have a PEM or org id set
            self.advanced = bool(self.pem_content or self.private_key_path or self.org_id)
        else:
            self.advanced = bool(advanced)

        # Compute available auth mechanisms
        self._has_api_keys = bool(self.api_key and self.api_secret)
        self._has_passphrase = bool(self.passphrase)
        self._has_jwt_ability = bool(self.pem_content or self.private_key_path)

        logger.info(f"nija_client startup: loading Coinbase auth config")
        logger.info(f" - base={self.base}")
        logger.info(f" - advanced={self.advanced}")
        logger.info(f" - jwt_set={'yes' if self._has_jwt_ability else 'no'}")
        logger.info(f" - api_key_set={'yes' if self._has_api_keys else 'no'}")
        logger.info(f" - api_passphrase_set={'yes' if self._has_passphrase else 'no'}")
        logger.info(f" - org_id_set={'yes' if bool(self.org_id) else 'no'}")
        logger.info(f" - private_key_path_set={'yes' if bool(self.private_key_path) else 'no'}")

        # Sanity checks: we don't throw on import, but initialization should surface missing credentials
        if not self._has_api_keys and not self._has_jwt_ability:
            # No credentials at all: warn but don't raise here; other code may expect exception later
            logger.warning("No Coinbase API keys or PEM found. Calls that require auth will fail.")
        else:
            logger.success("Found at least one authentication method (JWT or API key/secret).")

    # ---- Public API ----

    def get_accounts(self) -> List[Dict[str, Any]]:
        """
        External-facing method other modules call. Returns a list of account dicts (possibly empty).
        This method handles authentication (JWT or HMAC) and will try multiple candidate endpoints.
        """
        try:
            accounts = self._fetch_accounts_try_endpoints()
            if not accounts:
                logger.warning("No accounts returned (empty list). If you expect accounts, check key permissions and COINBASE_API_BASE.")
            return accounts
        except Exception as exc:
            logger.error(f"Failed to fetch Coinbase accounts: {exc}")
            return []

    # ---- Internal helpers ----

    def _fetch_accounts_try_endpoints(self) -> List[Dict[str, Any]]:
        """
        Try candidate endpoints under self.base. Return parsed JSON account list or raise on fatal issues.
        """
        if not (self._has_api_keys or self._has_jwt_ability):
            raise RuntimeError("Missing Coinbase credentials (API key/secret or PEM).")

        session = requests.Session()
        headers_common = {"User-Agent": "NIJA-Client/1.0"}

        last_exc: Optional[Exception] = None
        for endpoint in CANDIDATE_ACCOUNT_ENDPOINTS:
            url = self.base.rstrip("/") + endpoint
            logger.info(f"Trying Coinbase accounts endpoint: {url}")

            # Build headers and auth per current available method
            try:
                if self.advanced and self._has_jwt_ability and _HAS_PYJWT and _HAS_CRYPTO:
                    # Prefer JWT signing for Advanced if we have everything
                    headers = headers_common.copy()
                    headers.update(self._jwt_auth_headers())
                    resp = session.get(url, headers=headers, timeout=10)
                else:
                    # Fall back to HMAC-style headers compatible with retail Advanced/HMAC
                    headers = headers_common.copy()
                    # note: some advanced APIs require different HMAC forms; we implement a common one here
                    headers.update(self._hmac_headers("GET", endpoint, body=""))
                    resp = session.get(url, headers=headers, timeout=10)

                # Handle common statuses
                if resp.status_code == 200:
                    data = resp.json()
                    # Many Coinbase endpoints embed accounts under 'data' or return list directly
                    if isinstance(data, dict) and "data" in data:
                        accounts = data["data"]
                    elif isinstance(data, list):
                        accounts = data
                    else:
                        accounts = data
                    logger.success(f"Fetched accounts from {url} (count={len(accounts) if hasattr(accounts,'__len__') else 'unknown'})")
                    return accounts if isinstance(accounts, list) else [accounts]
                elif resp.status_code in (401, 403):
                    logger.warning(f"Authentication/permission error when fetching accounts ({resp.status_code}) for {url}. Check API keys and permissions.")
                    last_exc = RuntimeError(f"Auth error {resp.status_code}: {resp.text}")
                    # Don't immediately raise — try next candidate endpoint (maybe different auth needed)
                    continue
                elif resp.status_code == 404:
                    logger.warning(f"Endpoint not found (404) for {url}. Trying other candidate endpoints.")
                    last_exc = RuntimeError("404 Not Found")
                    continue
                else:
                    # Unexpected status: log and try next
                    logger.warning(f"HTTP error for {url}: {resp.status_code} {resp.text}")
                    last_exc = RuntimeError(f"{resp.status_code} {resp.text}")
                    continue

            except requests.RequestException as re:
                logger.warning(f"Network/Request exception while fetching accounts: {re}")
                last_exc = re
                continue
            except Exception as e:
                logger.exception(f"Unexpected exception while fetching accounts: {e}")
                last_exc = e
                continue

        # If we exit loop without a successful call, raise the last error to signal failure to caller.
        raise RuntimeError(f"Failed to fetch Coinbase accounts. Tried candidate endpoints and none returned a successful response. Check COINBASE_API_BASE, API keys, and that the API key has permissions to list accounts. Last error: {last_exc}")

    def _load_private_key(self) -> Optional[str]:
        """Return PEM content string if available, else None."""
        if self.pem_content:
            return self.pem_content
        if self.private_key_path and os.path.exists(self.private_key_path):
            try:
                with open(self.private_key_path, "r", encoding="utf-8") as fh:
                    return fh.read()
            except Exception as exc:
                logger.error(f"Failed to read private key file {self.private_key_path}: {exc}")
                return None
        return None

    def _jwt_auth_headers(self) -> Dict[str, str]:
        """
        Generate Authorization headers with a short-lived JWT generated from the service key (PEM).
        Requires PyJWT with crypto backend and cryptography installed for ES256.
        """
        if not _HAS_PYJWT or not _HAS_CRYPTO:
            logger.warning("PyJWT[crypto] or cryptography not available — cannot generate ES256 JWT. Falling back to HMAC where possible.")
            return {}

        key = self._load_private_key()
        if not key:
            logger.warning("No private key available for JWT generation.")
            return {}

        now = int(time.time())
        payload = {
            # standard JWT claims for Coinbase service key usage; adjust as Coinbase docs require
            "iss": self.org_id or (self.api_key or "nija-client"),
            "iat": now,
            "exp": now + 60,  # short-lived token
            "sub": self.api_key or "nija-client",
            "jti": f"nija-{now}"
        }
        # Use ES256 for Coinbase service keys (typical), but allow override if needed
        alg = "ES256"
        try:
            token = jwt.encode(payload, key, algorithm=alg)
            headers = {"Authorization": f"Bearer {token}"}
            # Some Advanced endpoints also expect an org id header
            if self.org_id:
                headers["CB-ORG-ID"] = self.org_id
            return headers
        except Exception as exc:
            logger.exception(f"Failed to generate JWT (ES256). Exception: {exc}")
            return {}

    def _hmac_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """
        Build HMAC style headers compatible with Coinbase REST (CB-ACCESS-SIGN-like) or generic HMAC.
        This is a conservative implementation; if your API key uses a different HMAC scheme, replace this.
        """
        if not self._has_api_keys:
            return {}

        # timestamp
        ts = str(int(time.time()))
        # message: timestamp + method + path + body
        msg = ts + method.upper() + path + (body or "")
        # If API secret is base64, we try to decode it else use raw bytes
        secret = self.api_secret
        try:
            secret_bytes = base64.b64decode(secret)
        except Exception:
            secret_bytes = secret.encode("utf-8")

        signature = hmac.new(secret_bytes, msg.encode("utf-8"), hashlib.sha256).digest()
        sig_hex = base64.b64encode(signature).decode("utf-8")

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig_hex,
            "CB-ACCESS-TIMESTAMP": ts,
        }
        if self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        return headers

    # Utilities
    @staticmethod
    def parse_accounts_response(raw: Any) -> List[Dict[str, Any]]:
        """Normalize various Coinbase account response types into a list of dicts."""
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            if "data" in raw and isinstance(raw["data"], list):
                return raw["data"]
            # single account object
            return [raw]
        return [raw]

    # For compatibility with older code that might call 'list_accounts'
    def list_accounts(self) -> List[Dict[str, Any]]:
        return self.get_accounts()


# If run as a script, perform a safe dry-run fetch (debugging helper)
if __name__ == "__main__":
    logger.info("nija_client module executed as script — performing dry run get_accounts()")
    c = CoinbaseClient()
    try:
        accounts = c.get_accounts()
        logger.info(f"Dry-run accounts result: {accounts}")
    except Exception as e:
        logger.exception("Dry-run failed: %s", e)
