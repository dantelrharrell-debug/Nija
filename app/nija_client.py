# nija_client.py
# Replace the existing file with this version.
# Purpose: Safe, non-crashing Coinbase client initializer which prefers JWT (Coinbase Advanced/CDP),
# tries common endpoints, and logs actionable guidance on failures.

import os
import time
import json
import requests
from loguru import logger
from typing import List, Dict, Optional

# --- Configuration defaults (env overrides in your Render / Railway / .env) ---
DEFAULT_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")  # user settable
JWT_ENV = "COINBASE_JWT"
API_KEY_ENV = "COINBASE_API_KEY"
API_SECRET_ENV = "COINBASE_API_SECRET"
API_PASSPHRASE_ENV = "COINBASE_API_PASSPHRASE"
ORG_ENV = "COINBASE_ORG_ID"
PRIVATE_KEY_PATH_ENV = "COINBASE_PRIVATE_KEY_PATH"

# Candidate endpoints to try (order matters: prefer CDP EVm accounts first per your logs)
CANDIDATE_ENDPOINTS = [
    "/platform/v2/evm/accounts",
    "/v2/accounts",
    "/v2/wallet/accounts",  # optional fallback candidate
]

class CoinbaseClient:
    """
    Lightweight, safe Coinbase client initializer.
    - Prefers COINBASE_JWT when present (recommended for Coinbase Advanced / CDP).
    - Will attempt candidate endpoints and return accounts list or empty list.
    - Will not raise exceptions that crash the process on auth/fetch failures.
    - Logs detailed actionable messages.
    """

    def __init__(self, advanced: bool = True, base: Optional[str] = None):
        self.advanced = advanced
        self.base = base or DEFAULT_BASE
        self.jwt = os.getenv(JWT_ENV)
        self.api_key = os.getenv(API_KEY_ENV)
        self.api_secret = os.getenv(API_SECRET_ENV)
        self.api_passphrase = os.getenv(API_PASSPHRASE_ENV)  # standard retail API requires this sometimes
        self.org_id = os.getenv(ORG_ENV)
        self.private_key_path = os.getenv(PRIVATE_KEY_PATH_ENV, "coinbase_private_key.pem")

        logger.info("Loaded Coinbase client environment:")
        logger.info(f" - base={self.base}")
        logger.info(f" - jwt_set={'yes' if self.jwt else 'no'}")
        logger.info(f" - api_key_set={'yes' if self.api_key else 'no'}")
        logger.info(f" - api_secret_set={'yes' if self.api_secret else 'no'}")
        logger.info(f" - api_passphrase_set={'yes' if self.api_passphrase else 'no'}")
        logger.info(f" - org_id_set={'yes' if self.org_id else 'no'}")
        logger.info(f"Advanced mode requested: {self.advanced}")

        # Basic validation but DO NOT crash the process — only log.
        if not (self.jwt or (self.api_key and self.api_secret)):
            logger.error("Coinbase API credentials are not set. Please set either COINBASE_JWT (preferred for Advanced/CDP) "
                         "or COINBASE_API_KEY and COINBASE_API_SECRET for HMAC-based access.")
            # don't raise — allow process to continue; fetch_accounts() will return [].
        else:
            logger.success("Required environment variables appear present (at least one auth method).")

        # Try to fetch accounts now (best-effort; never raise)
        try:
            accounts = self.fetch_accounts()
            if accounts:
                logger.success(f"Fetched {len(accounts)} account(s) from Coinbase.")
            else:
                logger.warning("No accounts returned from Coinbase (empty list). Check key permissions and endpoint.")
        except Exception as e:
            # Defensive: catch-all to avoid crashing the container
            logger.exception(f"Unexpected error when fetching accounts (caught): {e}")

    # ---- helpers ----
    def _bearer_headers(self, jwt_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nija-client/1.0",
        }

    def _try_get(self, url: str, headers: Dict[str, str], timeout: int = 8) -> Optional[requests.Response]:
        """Perform GET with safe exception handling. Returns Response or None."""
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            return resp
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network/Request exception for {url}: {e}")
            return None

    # ---- main fetch flow ----
    def fetch_accounts(self) -> List[Dict]:
        """
        Tries candidate endpoints with available auth.
        Returns a list of accounts (dicts) or [] on failure.
        """
        # 1) If JWT present — preferred path for Advanced/CDP
        if self.jwt:
            logger.info("Using JWT auth path (COINBASE_JWT present). Trying candidate endpoints.")
            headers = self._bearer_headers(self.jwt)
            for path in CANDIDATE_ENDPOINTS:
                url = self._join(self.base, path)
                logger.info(f"Trying Coinbase accounts endpoint: {url}")
                resp = self._try_get(url, headers)
                if resp is None:
                    continue
                if resp.status_code == 200:
                    logger.info(f"Success on {url} (200). Parsing response.")
                    try:
                        payload = resp.json()
                        accounts = self._extract_accounts_from_payload(payload)
                        return accounts
                    except Exception as e:
                        logger.exception(f"Failed parsing accounts JSON from {url}: {e}")
                        return []
                elif resp.status_code in (401, 403):
                    logger.error(f"Authentication/permission error when hitting {url}: {resp.status_code} {resp.reason}")
                    # include server body for debugging when available (don't leak secrets to logs)
                    body = self._safe_text(resp)
                    logger.debug(f"Response body (truncated): {body[:1000]}")
                    # If JWT yields 401/403, likely: wrong JWT, expired, wrong org, or permissions missing.
                    logger.warning("JWT auth returned 401/403. Verify your COINBASE_JWT was generated for the correct organization, "
                                   "and that the service key has accounts read permission. If you used a PEM to generate the JWT, ensure "
                                   "COINBASE_ORG_ID is correct.")
                    # stop trying other endpoints using JWT? continue to try remaining paths
                else:
                    logger.warning(f"Endpoint {url} returned {resp.status_code} ({resp.reason}) — trying next candidate.")
            logger.error("Tried all candidate endpoints with JWT and none succeeded. Check COINBASE_JWT, COINBASE_ORG_ID and key permissions.")
            return []

        # 2) If no JWT, but API_KEY/API_SECRET present — give clear guidance
        if self.api_key and self.api_secret:
            logger.info("No JWT found; API key + secret found. Attempting non-JWT guidance path.")
            # We intentionally do not attempt a fragile HMAC signing flow here to avoid breaking
            # — in many setups the signing method differs between retail, pro, and advanced CDP.
            # Instead, provide precise log guidance for the user to:
            #  - create a Service Key and use JWT (recommended), or
            #  - confirm HMAC style and add code to generate HMAC if needed.
            logger.warning(
                "Automatic HMAC signing is not enabled in this safe client. Two recommended actions:\n"
                "1) Create a Service Key in Coinbase Advanced (downloads PEM) and use the generate_jwt.py script to set COINBASE_JWT (recommended).\n"
                "2) OR if you require HMAC, ensure the API key has 'accounts.read' permission and use a dedicated HMAC signing function. "
                "If you want, I can paste a non-invasive HMAC sign snippet for your specific API type (Advanced HMAC vs Retail)."
            )
            return []

        # 3) No credentials at all
        logger.error("No usable Coinbase authentication configured (neither JWT nor API_KEY/API_SECRET). Returning empty accounts list.")
        return []

    # ---- small utilities ----
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
            return "<unreadable response body>"

    def _extract_accounts_from_payload(self, payload: Dict) -> List[Dict]:
        """
        Tries a few common payload shapes and returns a list of account dicts.
        This is intentionally flexible because Coinbase/CDP responses vary.
        """
        # Common: top-level "data" is list of accounts
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                return payload["data"]
            # Some CDP endpoints might wrap differently:
            if "accounts" in payload and isinstance(payload["accounts"], list):
                return payload["accounts"]
        # If payload itself is list
        if isinstance(payload, list):
            return payload
        logger.debug("Unrecognized accounts payload shape; returning empty list.")
        return []

# If this module is run directly, give quick diagnostic output.
if __name__ == "__main__":
    logger.info("Running nija_client.py diagnostic run (standalone).")
    client = CoinbaseClient()
    logger.info("Diagnostic finished.")
