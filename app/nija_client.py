# nija_client.py  -- put this in the project root (same folder as start_bot.py)
import os, time, hmac, hashlib, requests
import jwt
from loguru import logger

class CoinbaseClient:
    """
    Canonical Coinbase client for the Nija bot.
    Usage:
      client = CoinbaseClient(advanced=True)  # advanced -> JWT (CDP)
      client = CoinbaseClient(advanced=False) # standard HMAC API
      client = CoinbaseClient(advanced=True, base="https://api.cdp.coinbase.com")
    """

    def __init__(self, advanced=False, base=None, debug=False):
        self.advanced = bool(advanced)
        self.debug = bool(debug)

        if self.advanced:
            # Advanced (JWT) mode
            self.base = base or os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
            self.iss = os.getenv("COINBASE_ISS", "")  # expected to be key id (UUID)
            # Support PEM saved with literal "\n" or real newlines
            self.pem = os.getenv("COINBASE_PEM_CONTENT", "").replace("\\n", "\n")
            if not self.iss or not self.pem:
                logger.warning("Missing COINBASE_ISS or COINBASE_PEM_CONTENT. JWT calls will fail.")
            else:
                try:
                    self._generate_jwt()
                except Exception as e:
                    logger.error("JWT creation failed: %s", e)
        else:
            # Standard HMAC mode
            self.base = base or os.getenv("COINBASE_API_BASE", "https://api.coinbase.com/v2")
            self.api_key = os.getenv("COINBASE_API_KEY", "")
            self.api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
            if not self.api_key or not self.api_secret:
                logger.warning("Missing COINBASE_API_KEY or COINBASE_API_SECRET. HMAC calls will fail.")

        logger.info("CoinbaseClient initialized. advanced=%s base=%s", self.advanced, self.base)

    def _generate_jwt(self):
        payload = {"iss": self.iss, "iat": int(time.time()), "exp": int(time.time()) + 300}
        # jwt.encode returns str for PyJWT>=2; handle potential bytes
        token = jwt.encode(payload, self.pem, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        self.token = token
        logger.info("JWT generated (len=%d)", len(token))

    def _hmac_headers(self, method, request_path, body=""):
        ts = str(int(time.time()))
        message = ts + method.upper() + request_path + (body or "")
        sig = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-VERSION": os.getenv("CB_VERSION", "2025-11-11"),
        }
        return headers

    def _request(self, method, endpoint, body=None, timeout=10):
        url = self.base.rstrip("/") + endpoint
        headers = {}
        if self.advanced:
            if not hasattr(self, "token"):
                logger.warning("No JWT token present.")
            headers["Authorization"] = f"Bearer {getattr(self, 'token', '')}"
        else:
            # HMAC sign for standard API (v2 endpoints)
            headers = self._hmac_headers(method, endpoint, body or "")

        try:
            r = requests.request(method, url, headers=headers, data=body, timeout=timeout)
        except Exception as e:
            logger.warning("Request to %s failed: %s", url, e)
            return None, None

        # Return both status and text/json for debugging
        text = None
        try:
            text = r.text
        except Exception:
            text = "<no text>"

        if r.status_code >= 400:
            logger.warning("HTTP %s for %s: %s", r.status_code, url, text[:400])
            return r.status_code, text

        # Try json, fallback to text
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, text

    def get_accounts(self):
        """
        Try several candidate endpoints (some return 404 depending on base and account).
        Returns (status, data) or (None, None) on network failure.
        """
        candidates = ["/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/api/v3/trading/accounts", "/api/v3/portfolios"]
        for ep in candidates:
            status, data = self._request("GET", ep)
            if status is None:
                # network error; try next
                continue
            if status == 200:
                logger.info("Fetched accounts from %s", ep)
                return status, data
            # keep trying until we find a successful endpoint
            logger.debug("Endpoint %s returned %s", ep, status)
        logger.error("Failed to fetch accounts from any candidate endpoint.")
        return None, None
