# nija_hmac_client.py
import os
import time
import json
import logging
import base64
import hmac
import hashlib
import requests

logger = logging.getLogger("nija_hmac_client")
logging.basicConfig(level=logging.INFO)

COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
# Advanced / CDP variables (JWT)
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # full PEM string
COINBASE_ISS = os.getenv("COINBASE_ISS")  # API key id (issuer)
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")  # optional
# Retail/HMAC vars
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# Utility: safe json parse
def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        # return text if it's not valid JSON
        return resp.text

class CoinbaseClient:
    def __init__(self):
        self.base = COINBASE_API_BASE.rstrip("")
        self.advanced = bool(COINBASE_PEM_CONTENT and COINBASE_ISS)
        if self.advanced:
            logger.info("Using Coinbase Advanced (v3) mode (JWT).")
        else:
            logger.info("Using Coinbase Retail HMAC mode.")
        # basic checks
        if self.advanced:
            if not COINBASE_PEM_CONTENT or not COINBASE_ISS:
                raise ValueError("Advanced keys not fully set (COINBASE_PEM_CONTENT/COINBASE_ISS).")
        else:
            if not (COINBASE_API_KEY and COINBASE_API_SECRET):
                logger.warning("Retail HMAC keys missing; calls will fail unless you set them.")

    # --- Advanced JWT builder (minimal ES256 using PyJWT if available) ---
    def _build_jwt(self, method, path):
        """
        Build a short-lived JWT for the Advanced (CDP) endpoints.
        This code tries to use PyJWT if installed. If not available, raises.
        """
        try:
            import jwt  # PyJWT
        except Exception as e:
            raise RuntimeError("PyJWT required for Advanced JWT generation. Install pyjwt or use Retail HMAC.") from e

        # Ensure path is full API path format for JWT signing per Coinbase docs:
        # e.g. "GET api.coinbase.com/api/v3/brokerage/accounts"
        # note: jwt.payload 'iss' is the API key id
        now = int(time.time())
        payload = {
            "iss": COINBASE_ISS,
            "iat": now,
            "exp": now + 60  # short lived token
        }
        if COINBASE_ORG_ID:
            payload["org_id"] = COINBASE_ORG_ID

        # Format the "uri" as required by some libraries: method + ' ' + host + path
        # but coinbase examples often sign using path like: "GET api.coinbase.com/api/v3/brokerage/accounts"
        host = self.base.replace("https://", "").replace("http://", "")
        uri = f"{method.upper()} {host}{path}"
        # put uri in header or claim if your library requires it. Some implementations require the exact formatting.
        headers = {"typ": "JWT"}
        # use the PEM string to sign
        private_key = COINBASE_PEM_CONTENT
        token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
        return token

    # --- Retail HMAC signature (CB-ACCESS-SIGN style) ---
    def _hmac_headers(self, method, path, body=""):
        ts = str(int(time.time()))
        method_up = method.upper()
        prehash = ts + method_up + path + (body or "")
        signature = base64.b64encode(hmac.new(COINBASE_API_SECRET.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        headers = {
            "CB-ACCESS-KEY": COINBASE_API_KEY,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": COINBASE_API_PASSPHRASE or "",
            "Content-Type": "application/json"
        }
        return headers

    def request(self, method="GET", path="/api/v3/brokerage/accounts", data=None, timeout=15):
        """
        Generic request. Returns (status_code, parsed_or_text)
        - For Advanced mode: creates a JWT and sets Authorization Bearer header.
        - For retail: uses HMAC headers.
        """
        # Normalize path: allow callers to pass e.g. "/v3/accounts" or "/api/v3/brokerage/accounts"
        if path.startswith("/v3/") or path.startswith("/v2/"):
            # convert common variants to canonical brokerage path if needed
            if path.startswith("/v3/") and "brokerage" not in path:
                # common mistake: /v3/accounts -> correct: /api/v3/brokerage/accounts
                logger.debug("Rewriting incoming path to /api/v3/brokerage/accounts")
                path = "/api/v3/brokerage/accounts"
        if not path.startswith("/"):
            path = "/" + path

        url = self.base + path
        body = json.dumps(data) if data else ""

        try:
            if self.advanced:
                try:
                    token = self._build_jwt(method, path)
                except Exception as e:
                    logger.exception("Advanced JWT generation failed: %s", e)
                    return 500, f"Advanced JWT generation failed: {e}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                resp = requests.request(method, url, headers=headers, data=body if body else None, timeout=timeout)
            else:
                if not (COINBASE_API_KEY and COINBASE_API_SECRET):
                    logger.error("HMAC keys not configured (COINBASE_API_KEY / COINBASE_API_SECRET).")
                    return 500, "HMAC keys missing"
                headers = self._hmac_headers(method, path, body)
                resp = requests.request(method, url, headers=headers, data=body if body else None, timeout=timeout)

            # parse safely
            status = resp.status_code
            try:
                parsed = resp.json()
                return status, parsed
            except Exception:
                # log raw body for diagnostics
                text = resp.text
                logger.warning("⚠️ JSON decode failed. Status: %s, Body: %s", status, (text[:400] + '...') if len(text) > 400 else text)
                return status, text
        except requests.RequestException as e:
            logger.exception("HTTP request failed: %s", e)
            return 500, str(e)
