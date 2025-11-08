# nija_client.py
import os
import time
import hmac
import hashlib
import logging
from urllib.parse import urljoin, urlparse
import requests
from typing import Optional

logger = logging.getLogger("nija_client")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class CoinbaseClient:
    """
    Minimal, robust Coinbase client used by Nija to fetch accounts.
    - Tries HMAC-style auth first (existing behavior).
    - If HMAC returns 401, and COINBASE_JWT env var is set, tries Bearer JWT fallback.
    - Does not execute anything at import time (no side effects).
    """

    def __init__(self, advanced: bool = True):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.advanced = bool(advanced)
        # Optional explicit JWT (you may generate via your repo scripts). If present, will be tried as fallback.
        self.jwt_token = os.getenv("COINBASE_JWT")

        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API key and secret must be set")
        if not self.advanced and not self.passphrase:
            raise ValueError("Coinbase API passphrase must be set for standard API")

        logger.info(f"CoinbaseClient initialized (Advanced={self.advanced}, base={self.base_url})")

        # Candidate endpoints to try (order matters; advanced candidates first, then standard fallback).
        self._candidate_paths = [
            "/platform/v2/evm/accounts",
            "/platform/v2/accounts",
            "/v2/accounts",  # fallback to standard API route if needed
        ]

    def _sign_hmac(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """
        Produce a HMAC hex signature using the raw API secret.
        Keep consistent with your existing signing method.
        """
        message = timestamp + method.upper() + request_path + (body or "")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _build_hmac_headers(self, signature: str, timestamp: str, use_passphrase: bool = False) -> dict:
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if use_passphrase and self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        return headers

    def _build_jwt_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _try_get(self, url: str, headers: dict, timeout: float = 10.0):
        """
        Single GET helper that raises on HTTP error (so caller can react).
        """
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp

    def get_accounts(self, timeout: float = 10.0):
        """
        Attempt to fetch accounts by iterating candidate endpoints.
        Workflow:
        1) For each candidate endpoint, try HMAC-signed request.
        2) If HMAC returns 401 and COINBASE_JWT is set, try the JWT bearer token for the same endpoint.
        3) On success return resp.json(); otherwise after trying all, raise RuntimeError with logged context.
        """
        last_exc: Optional[Exception] = None

        for path in self._candidate_paths:
            url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
            parsed = urlparse(url)
            request_path = parsed.path or "/"
            if parsed.query:
                request_path += "?" + parsed.query

            timestamp = str(int(time.time()))
            method = "GET"
            body = ""

            # 1) Try HMAC auth first
            try:
                signature = self._sign_hmac(timestamp, method, request_path, body)
                use_pass = (path == "/v2/accounts" and not self.advanced)
                headers = self._build_hmac_headers(signature, timestamp, use_passphrase=use_pass)

                logger.info(f"Trying accounts endpoint with HMAC: {url}")
                resp = self._try_get(url, headers=headers, timeout=timeout)
                logger.info(f"Accounts fetched successfully from {path} (status {resp.status_code}) via HMAC")
                return resp.json()

            except requests.exceptions.HTTPError as he:
                status = getattr(he.response, "status_code", None)
                logger.warning(f"HTTP error for {url} (HMAC): {he} (status {status})")
                last_exc = he

                # If 401 and JWT token available, attempt JWT fallback
                if status == 401 and self.jwt_token:
                    try:
                        jwt_headers = self._build_jwt_headers(self.jwt_token)
                        logger.info(f"HMAC returned 401; trying same endpoint with JWT Bearer for {url}")
                        resp = self._try_get(url, headers=jwt_headers, timeout=timeout)
                        logger.info(f"Accounts fetched successfully from {path} (status {resp.status_code}) via JWT")
                        return resp.json()
                    except requests.exceptions.HTTPError as he2:
                        status2 = getattr(he2.response, "status_code", None)
                        logger.warning(f"HTTP error for {url} (JWT): {he2} (status {status2})")
                        last_exc = he2
                        # If JWT also fails, continue to next candidate endpoint
                        continue
                    except requests.exceptions.RequestException as re2:
                        logger.warning(f"Network error for {url} (JWT): {re2}")
                        last_exc = re2
                        continue

                # If 401/403 without JWT fallback — surface authentication/permission hint and break early
                if status in (401, 403) and not self.jwt_token:
                    logger.error("Authentication/permission error when fetching accounts (HMAC). "
                                 "If you're using Coinbase Advanced and keys require JWT, set COINBASE_JWT.")
                    break
                # otherwise continue to next candidate endpoint
                continue

            except requests.exceptions.RequestException as re:
                logger.warning(f"Network/Request exception while fetching accounts from {url} (HMAC): {re}")
                last_exc = re
                continue

            except Exception as e:
                logger.exception(f"Unexpected error when fetching accounts from {url} (HMAC): {e}")
                last_exc = e
                continue

        # If we exhausted candidates and got no success, raise helpful error
        msg = (
            "Failed to fetch Coinbase accounts. Tried candidate endpoints and none returned a successful response. "
            "Check COINBASE_API_BASE, COINBASE_API_KEY/SECRET (and COINBASE_API_PASSPHRASE if using standard API), "
            "or supply COINBASE_JWT if your Advanced key uses JWT authentication. Also verify the API key has 'list accounts' permission."
        )
        logger.error(msg)
        if last_exc:
            raise RuntimeError(msg) from last_exc
        raise RuntimeError(msg)
