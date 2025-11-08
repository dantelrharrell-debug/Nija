# nija_client.py
import os
import time
import hmac
import hashlib
import logging
from urllib.parse import urljoin, urlparse
import requests

# Use standard logging to avoid interfering with other libs; you can swap to loguru if you prefer.
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
    - Does not change trading logic.
    - Tries advanced endpoints first (multiple likely Advanced paths).
    - Falls back to standard v2/accounts if needed.
    """

    def __init__(self, advanced: bool = True):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        # Default base for Coinbase Advanced / CDP is api.cdp.coinbase.com
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.advanced = bool(advanced)

        # minimal credential validation (won't enforce passphrase for advanced)
        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API key and secret must be set")
        if not self.advanced and not self.passphrase:
            raise ValueError("Coinbase API passphrase must be set for standard API")

        logger.info(f"CoinbaseClient initialized (Advanced={self.advanced}, base={self.base_url})")

        # Candidate endpoints (try in order). Advanced endpoints first.
        self._advanced_paths = [
            "/platform/v2/evm/accounts",   # known Advanced EVM/accounts path
            "/platform/v2/accounts",       # possible Advanced variant
            "/v2/accounts",                # standard API (fallback)
        ]

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """
        Build HMAC signature compatible with current codebase.
        Keep this consistent with how your system expects headers.
        """
        message = timestamp + method.upper() + request_path + (body or "")
        # If api_secret is base64 or PEM-based, adapt here. This uses raw secret as hex/hmac key.
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _build_headers(self, signature: str, timestamp: str, use_passphrase: bool = False) -> dict:
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if use_passphrase and self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        return headers

    def get_accounts(self, timeout: float = 10.0):
        """
        Attempts to fetch accounts. Tries multiple candidate endpoints in order.
        Returns the parsed JSON response on success, or raises an exception on total failure.
        """
        last_exc = None

        for path in self._advanced_paths:
            url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
            parsed = urlparse(url)
            request_path = parsed.path or "/"
            if parsed.query:
                request_path += "?" + parsed.query

            timestamp = str(int(time.time()))
            method = "GET"
            body = ""  # no body for GET

            try:
                signature = self._sign(timestamp, method, request_path, body)
                # Only include passphrase for the standard API path (/v2/accounts). If using advanced, don't add.
                use_pass = path == "/v2/accounts" and not self.advanced
                headers = self._build_headers(signature, timestamp, use_passphrase=use_pass)

                logger.info(f"Trying Coinbase accounts endpoint: {url}")
                resp = requests.get(url, headers=headers, timeout=timeout)
                # If 404 on a candidate advanced path, we proceed to next candidate.
                resp.raise_for_status()

                # success
                logger.info(f"Accounts fetched successfully from {path} (status {resp.status_code})")
                # Return JSON content as-is; calling code can parse structure.
                return resp.json()

            except requests.exceptions.HTTPError as he:
                status = getattr(he.response, "status_code", None)
                logger.warning(f"HTTP error for {url}: {he} (status {status})")
                last_exc = he
                # For 404/403 try next candidate; for 401 it's likely credentials issue so break and surface error
                if status in (401, 403):
                    logger.error("Authentication/permission error when fetching accounts. Check API keys and permissions.")
                    break
                else:
                    # continue to try other endpoints
                    continue

            except requests.exceptions.RequestException as re:
                logger.warning(f"Network/Request exception while fetching accounts from {url}: {re}")
                last_exc = re
                # continue to next candidate
                continue

            except Exception as e:
                logger.exception(f"Unexpected error when fetching accounts from {url}: {e}")
                last_exc = e
                continue

        # if we've tried all endpoints and none succeeded, raise a helpful error
        msg = (
            "Failed to fetch Coinbase accounts. "
            "Tried candidate endpoints and none returned a successful response. "
            "Check COINBASE_API_BASE, API keys, and that the API key has permissions to list accounts."
        )
        logger.error(msg)
        if last_exc:
            # raise the last caught exception chained to provide context
            raise RuntimeError(msg) from last_exc
        raise RuntimeError(msg)
