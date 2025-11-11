# app/nija_client.py
"""
CoinbaseClient supporting:
 - HMAC (standard) mode using COINBASE_API_KEY / COINBASE_API_SECRET
 - Advanced (JWT) mode using COINBASE_ISS / COINBASE_PEM_CONTENT
This file intentionally DOES NOT contain any secrets.
Secrets must be provided via env vars (Railway / .env).
"""

import os
import time
import logging
import hmac
import hashlib
import requests
import json

# Optional dependency: PyJWT. If using advanced mode ensure it's installed.
try:
    import jwt  # PyJWT
except Exception:
    jwt = None  # we'll handle absence gracefully

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# Env var names
ENV = {
    "HMAC_KEY": "COINBASE_API_KEY",
    "HMAC_SECRET": "COINBASE_API_SECRET",
    "HMAC_PASSPHRASE": "COINBASE_API_PASSPHRASE",
    "HMAC_BASE": "COINBASE_API_BASE",
    "ADV_ISS": "COINBASE_ISS",
    "ADV_PEM": "COINBASE_PEM_CONTENT",
    "ADV_BASE": "COINBASE_ADVANCED_BASE",
}

# Defaults
DEFAULTS = {
    "HMAC_BASE": "https://api.coinbase.com",
    "ADV_BASE": "https://api.cdp.coinbase.com",
}


class CoinbaseClient:
    def __init__(self, advanced: bool | None = None, debug: bool = False):
        """
        If advanced is None: auto-detect mode from env
        advanced=True forces JWT mode, advanced=False forces HMAC mode.
        """
        if debug:
            logger.setLevel(logging.DEBUG)

        # Load env
        self.hmac_key = os.getenv(ENV["HMAC_KEY"])
        self.hmac_secret = os.getenv(ENV["HMAC_SECRET"])
        self.hmac_passphrase = os.getenv(ENV["HMAC_PASSPHRASE"]) or ""
        self.hmac_base = os.getenv(ENV["HMAC_BASE"]) or DEFAULTS["HMAC_BASE"]

        self.adv_iss = os.getenv(ENV["ADV_ISS"])
        self.adv_pem = os.getenv(ENV["ADV_PEM"])
        self.adv_base = os.getenv(ENV["ADV_BASE"]) or DEFAULTS["ADV_BASE"]

        # Mode selection
        if advanced is True:
            self.mode = "advanced"
        elif advanced is False:
            self.mode = "hmac"
        else:
            # auto-detect: prefer advanced if both present
            if self.adv_iss and self.adv_pem:
                self.mode = "advanced"
            elif self.hmac_key and self.hmac_secret:
                self.mode = "hmac"
            else:
                self.mode = "unknown"

        logger.info("CoinbaseClient initialized. mode=%s base=%s", self.mode,
                    self.adv_base if self.mode == "advanced" else self.hmac_base)

    # -----------------------
    # Public API
    # -----------------------
    def get_accounts(self):
        """Public method used by your start script. Returns (status_code, body_or_error)."""
        if self.mode == "advanced":
            return self.get_accounts_advanced()
        elif self.mode == "hmac":
            return self.get_accounts_hmac()
        else:
            return None, "No valid Coinbase credentials found in env"

    # -----------------------
    # HMAC / Standard methods
    # -----------------------
    def _hmac_headers(self, method: str, path: str, body: str = ""):
        if not (self.hmac_key and self.hmac_secret):
            raise RuntimeError("Missing HMAC key/secret in environment")

        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        signature = hmac.new(
            self.hmac_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.hmac_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-VERSION": time.strftime("%Y-%m-%d"),
            "Content-Type": "application/json",
        }
        if self.hmac_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.hmac_passphrase
        return headers

    def get_accounts_hmac(self):
        path = "/v2/accounts"
        url = self.hmac_base.rstrip("/") + path
        try:
            headers = self._hmac_headers("GET", path, "")
        except RuntimeError as e:
            logger.error("HMAC headers error: %s", e)
            return None, str(e)

        try:
            r = requests.get(url, headers=headers, timeout=10)
            logger.debug("HMAC GET %s -> %s", url, r.status_code)
            return r.status_code, r.text
        except Exception as e:
            logger.exception("HMAC request failed")
            return None, str(e)

    # -----------------------
    # Advanced / JWT methods
    # -----------------------
    def _create_jwt(self):
        if not jwt:
            raise RuntimeError("PyJWT not installed. Install with `pip install PyJWT`")

        if not (self.adv_iss and self.adv_pem):
            raise RuntimeError("Missing COINBASE_ISS or COINBASE_PEM_CONTENT")

        timestamp = int(time.time())
        payload = {"iss": self.adv_iss, "iat": timestamp, "exp": timestamp + 300}
        # Note: adv_pem must be full PEM string with line breaks
        token = jwt.encode(payload, self.adv_pem, algorithm="ES256")
        # PyJWT returns str in modern versions; ensure str
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    def get_accounts_advanced(self):
        path = "/accounts"
        url = self.adv_base.rstrip("/") + path
        try:
            token = self._create_jwt()
        except Exception as e:
            logger.error("JWT creation failed: %s", e)
            return None, str(e)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            logger.debug("ADV GET %s -> %s", url, r.status_code)
            return r.status_code, r.text
        except Exception as e:
            logger.exception("Advanced request failed")
            return None, str(e)

    # -----------------------
    # Utility: small test
    # -----------------------
    def test_connection(self):
        """Convenience helper used at startup to test whichever mode is active."""
        status, resp = self.get_accounts()
        if status == 200:
            logger.info("✅ Coinbase API reachable and authorized.")
        elif status in (401, 403):
            logger.warning("❌ Coinbase API unauthorized (status=%s). Check keys/permissions.", status)
        elif status is None:
            logger.error("❌ Coinbase test failed: %s", resp)
        else:
            logger.warning("Coinbase returned status=%s body=%s", status, resp)
        return status, resp


# If executed directly, we run a quick test using current env
if __name__ == "__main__":
    c = CoinbaseClient()
    print("Detected mode:", c.mode)
    sc, body = c.get_accounts()
    print("Status Code:", sc)
    print("Response:", body)
