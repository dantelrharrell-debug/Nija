# nija_client.py
# Coinbase client supporting both Classic HMAC signing and Advanced JWT (PEM ES256).
# Backwards-compatible helpers: get_all_accounts(), get_usd_spot_balance()
# Also provides calculate_position_size()

import os
import time
import json
import base64
import logging
import hmac
import hashlib
import requests
from typing import Any, Dict, List, Optional

try:
    import jwt  # PyJWT
except Exception:
    jwt = None  # we will check before using

LOG = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)


class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret_raw = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # normalize secrets
        if self.api_secret_raw and "\\n" in self.api_secret_raw:
            # common when storing PEM with escaped newlines
            self.api_secret_raw = self.api_secret_raw.replace("\\n", "\n").strip()

        # determine auth mode
        self.auth_mode = self._detect_auth_mode()
        LOG.info("🔍 Checking Coinbase credentials in environment...")
        if self.auth_mode == "advanced":
            LOG.info("✅ CoinbaseClient initialized (advanced JWT mode).")
        elif self.auth_mode == "classic":
            LOG.info("✅ CoinbaseClient initialized (classic HMAC mode).")
        else:
            LOG.warning("⚠️ No usable Coinbase credentials detected. Client in 'none' mode.")

        # optional quick preflight (non-fatal: errors will be logged)
        try:
            LOG.info("ℹ️ Running preflight check...")
            # don't crash in init; just log. callers can call wrappers to get exceptions if needed.
            _ = self.get_all_accounts()
            LOG.info("ℹ️ Preflight account fetch attempted.")
        except Exception as e:
            LOG.warning("❌ Preflight check failed: %s", e)

    def _detect_auth_mode(self) -> str:
        """Detect whether we have an Advanced PEM key or classic API secret."""
        if self.api_secret_raw and "BEGIN " in self.api_secret_raw and jwt:
            # looks like a PEM private key => Advanced JWT (ES256)
            return "advanced"
        if self.api_key and self.api_secret_raw:
            # have classic API key + secret -> classic HMAC
            return "classic"
        return "none"

    # ----------------------
    # Advanced JWT helpers
    # ----------------------
    def _generate_jwt(self, method: str, endpoint: str, body: Optional[str] = "") -> str:
        """
        Generate ES256 JWT using PEM private key in self.api_secret_raw.
        Payload uses standard iat/exp and includes request fields per Coinbase Advanced docs.
        """
        if not jwt:
            raise RuntimeError("PyJWT not available in environment.")
        if not self.api_secret_raw:
            raise RuntimeError("Missing API secret for JWT generation.")

        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,  # short-lived
            "sub": self.api_key or "",
            "method": (method or "GET").upper(),
            "request_path": endpoint,
            "body": body or "",
        }

        # jwt.encode will accept a PEM-formatted private key string for algorithm 'ES256'
        try:
            token = jwt.encode(payload, self.api_secret_raw, algorithm="ES256")
            # PyJWT 2.x returns str; older versions may return bytes
            if isinstance(token, bytes):
                token = token.decode()
            return token
        except Exception as e:
            LOG.error("❌ Failed to generate JWT: %s", e)
            raise

    # ----------------------
    # Classic HMAC helpers
    # ----------------------
    def _classic_sign(self, method: str, endpoint: str, body: Optional[str] = "") -> Dict[str, str]:
        """
        Classic Coinbase-style HMAC signing:
          prehash = timestamp + method + request_path + body
        Signature = base64encode(HMAC_SHA256(secret_bytes, prehash))
        Accepts secret either raw or base64-encoded.
        Returns headers dict to merge.
        """
        if not self.api_key or not self.api_secret_raw:
            raise RuntimeError("Missing API key or secret for classic signing.")
        ts = str(int(time.time()))
        body_str = body or ""
        prehash = ts + (method or "GET").upper() + endpoint + (body_str if body_str else "")

        # try base64 decode secret (common for some providers), fallback to raw bytes
        secret_bytes = None
        try:
            secret_bytes = base64.b64decode(self.api_secret_raw)
            # Some secrets decode into nonsense; if decoded is short we may still use it.
            if len(secret_bytes) < 8:
                # suspiciously short; fallback
                secret_bytes = self.api_secret_raw.encode()
        except Exception:
            secret_bytes = self.api_secret_raw.encode()

        sig = hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()
        signature = base64.b64encode(sig).decode()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": ts,
        }
        if self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        return headers

    # ----------------------
    # Generic request helper
    # ----------------------
    def _send_request(self, endpoint: str, method: str = "GET", data: Optional[Any] = None) -> Dict[str, Any]:
        """
        Send an HTTP request to Coinbase, using the detected auth mode.
        endpoint should start with / (e.g. "/v2/accounts")
        Returns parsed JSON (dict).
        Raises RuntimeError on HTTP error or invalid auth.
        """
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = self.base_url.rstrip("/") + endpoint

        body = None
        if data is not None:
            # if data is a dict, encode; else str()
            if isinstance(data, (dict, list)):
                body = json.dumps(data)
            else:
                body = str(data)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nija-client/1.0",
        }

        # choose auth
        if self.auth_mode == "advanced":
            try:
                token = self._generate_jwt(method, endpoint, body or "")
            except Exception as e:
                raise RuntimeError(f"❌ JWT generation failed: {e}")
            headers["Authorization"] = f"Bearer {token}"
        elif self.auth_mode == "classic":
            try:
                sig_headers = self._classic_sign(method, endpoint, body or "")
            except Exception as e:
                raise RuntimeError(f"❌ Classic signing failed: {e}")
            headers.update(sig_headers)
        else:
            LOG.warning("⚠️ No auth mode configured; sending unsigned request (likely to 401).")

        try:
            resp = requests.request(method, url, headers=headers, data=body, timeout=15)
        except Exception as e:
            LOG.error("❌ Request exception: %s", e)
            raise RuntimeError(f"❌ Request exception: {e}")

        if resp.status_code == 401:
            LOG.error("❌ Request failed (401). Response: %s", resp.text)
            raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
        if not resp.ok:
            LOG.error("❌ Request failed: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"❌ Request failed: {resp.status_code} {resp.text}")

        try:
            return resp.json()
        except Exception as e:
            LOG.error("❌ Failed to parse JSON response: %s", e)
            raise RuntimeError(f"❌ Failed to parse JSON response: {e}")

    # ----------------------
    # Public actions
    # ----------------------
    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """
        Returns list of account dicts (same shape as Coinbase /v2/accounts data array).
        Raises RuntimeError on failure.
        """
        payload = self._send_request("/v2/accounts", method="GET")
        # normalize
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        if isinstance(payload, list):
            return payload
        raise RuntimeError("❌ Unexpected accounts response shape")

    def get_usd_spot_balance(self) -> float:
        """
        Return USD spot balance as float. Raises on fatal failure.
        """
        accounts = self.get_all_accounts()
        # Coinbase v2 accounts have 'balance': {'currency': 'USD', 'amount':'0.0'} and account-level 'currency' in some APIs
        for acct in accounts:
            # account may have top-level currency or nested
            if acct.get("currency") == "USD":
                amt = acct.get("balance", {}).get("amount") if acct.get("balance") else acct.get("available") or acct.get("balance")
                try:
                    return float(acct.get("balance", {}).get("amount", 0))
                except Exception:
                    try:
                        return float(acct.get("available", 0))
                    except Exception:
                        continue
            # nested balance currency
            bal = acct.get("balance", {})
            if isinstance(bal, dict) and bal.get("currency") == "USD":
                try:
                    return float(bal.get("amount", 0))
                except Exception:
                    continue
        # if no USD account found, return 0 (caller can decide)
        return 0.0

    def place_market_order(self, product_id: str = "BTC-USD", side: str = "buy", funds: float = 10.0) -> Dict[str, Any]:
        """
        Place a simple market order. NOTE: Make sure your key has 'trade' permission.
        Uses POST /orders (Coinbase Create Order).
        """
        body = {
            "product_id": product_id,
            "side": side.lower(),
            "type": "market",
            "funds": str(funds),
        }
        return self._send_request("/orders", method="POST", data=body)


# -------------------------------
# Backwards-compatible module functions
# -------------------------------
def get_all_accounts() -> List[Dict[str, Any]]:
    client = CoinbaseClient()
    return client.get_all_accounts()


def get_usd_spot_balance() -> float:
    client = CoinbaseClient()
    return client.get_usd_spot_balance()


# -------------------------------
# Position sizing
# -------------------------------
def calculate_position_size(account_equity: float, risk_factor: float = 1.0, min_percent: int = 2, max_percent: int = 10) -> float:
    """
    Calculates position size for a trade based on account equity.

    account_equity : float : USD account balance
    risk_factor    : float : Multiplier for trade confidence (default=1.0)
    min_percent    : int   : Minimum % of equity to trade
    max_percent    : int   : Maximum % of equity to trade

    returns : float : Trade size in USD
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")

    # risk_factor is treated as a percent (e.g., 1.0 -> 1% of equity)
    raw_allocation = account_equity * (risk_factor / 100.0)

    # Clamp allocation between min and max percent
    min_alloc = account_equity * (min_percent / 100.0)
    max_alloc = account_equity * (max_percent / 100.0)

    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size


# Expose a client factory for convenience
def new_client() -> CoinbaseClient:
    return CoinbaseClient()

# Module-level quick-test when executed directly (safe: no secrets printed)
if __name__ == "__main__":
    LOG.info("🔍 [DEBUG] Starting CoinbaseClient quick test (no secrets printed).")
    try:
        c = CoinbaseClient()
        try:
            bal = c.get_usd_spot_balance()
            LOG.info("✅ USD Balance: %s", bal)
        except Exception as e:
            LOG.warning("⚠️ Could not fetch USD balance during quick test: %s", e)
    except Exception as e:
        LOG.error("❌ CoinbaseClient failed to initialize: %s", e)
