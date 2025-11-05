"""
nija_client.py

Single-file Coinbase Advanced / Base helper + position sizing helper.

Environment variables (set these in your Render/Railway service settings):
  - COINBASE_API_KEY        : your API key id (string)
  - COINBASE_API_SECRET     : your API secret OR PEM private key (for Advanced JWT).
                             If using PEM in env, it often is stored with literal '\n' sequences;
                             this module auto-fixes common formatting issues.
  - COINBASE_API_PASSPHRASE : OPTIONAL classic key passphrase (if you're using classic API keys)
  - COINBASE_API_BASE       : OPTIONAL, default "https://api.coinbase.com"

Notes:
 - This module prefers Advanced JWT (PEM + ES256). If COINBASE_API_SECRET contains PEM framing,
   it will attempt JWT auth. If you want to use classic CB-ACCESS headers instead, supply
   COINBASE_API_PASSPHRASE and adapt the code to your classic-key signing scheme.
 - Do NOT hardcode secrets here.
"""

import os
import time
import json
import logging
from typing import Optional, Dict, Any

import requests
import jwt  # PyJWT

LOG = logging.getLogger("nija_client")
if not LOG.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s: %(message)s")
    handler.setFormatter(formatter)
    LOG.addHandler(handler)
LOG.setLevel(logging.INFO)


class CoinbaseClient:
    def __init__(self, preflight: bool = True):
        # read environment
        self.api_key: Optional[str] = os.getenv("COINBASE_API_KEY")
        self.api_secret_raw: Optional[str] = os.getenv("COINBASE_API_SECRET")
        self.passphrase: Optional[str] = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url: str = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # Derived
        self.auth_mode = None  # 'jwt' or 'classic' or None
        self.pem_private_key: Optional[str] = None

        LOG.info("🔍 Checking Coinbase credentials in environment...")
        if self.api_secret_raw and "BEGIN" in self.api_secret_raw:
            # Likely an Advanced JWT PEM private key
            try:
                self.pem_private_key = self._fix_pem(self.api_secret_raw)
                self.auth_mode = "jwt"
                LOG.info("⚠️ No passphrase required for Advanced JWT keys.")
                LOG.info("✅ CoinbaseClient initialized (Advanced JWT mode).")
            except Exception as e:
                LOG.error("❌ PEM load/fix failed: %s", e)
                # leave auth_mode None so we can potentially fallback
        elif self.passphrase:
            # If there's a passphrase we assume classic API key flow (older Coinbase)
            self.auth_mode = "classic"
            LOG.info("✅ CoinbaseClient initialized (classic API key mode with passphrase).")
        elif self.api_key and self.api_secret_raw:
            # Non-PEM secret — could still be classic HMAC secret without passphrase
            self.auth_mode = "classic"
            LOG.info("✅ CoinbaseClient initialized (classic API key mode).")
        else:
            LOG.warning("⚠️ Coinbase credentials not fully present in env. Some features will fail.")

        # Optional preflight check
        if preflight:
            try:
                LOG.info("ℹ️ Running preflight check...")
                accounts = self.get_all_accounts()
                LOG.info("✅ Preflight check passed — accounts fetched: %d", len(accounts))
            except Exception as e:
                LOG.warning("❌ Preflight check failed: %s", e)

    # -----------------
    # Helpers
    # -----------------
    @staticmethod
    def _fix_pem(pem_str: str) -> str:
        """
        Fix PEM strings that were stored in env with literal "\n" sequences.
        Ensures correct BEGIN/END framing and returns a PEM string with real newlines.
        """
        if pem_str is None:
            raise ValueError("PEM string is None")
        pem = pem_str.strip()
        # Replace literal two-character backslash-n sequences with actual newlines
        pem = pem.replace("\\n", "\n")
        # Ensure proper framing lines exist
        if not (pem.startswith("-----BEGIN") and pem.strip().endswith("-----END EC PRIVATE KEY-----")):
            # Try to be lenient: look for BEGIN/END anywhere and extract
            if "-----BEGIN" in pem and "-----END" in pem:
                begin = pem.find("-----BEGIN")
                end = pem.find("-----END")
                pem = pem[begin:]
            else:
                raise ValueError("PEM content is malformed or missing BEGIN/END markers.")
        return pem

    def _generate_jwt(self, method: str = "GET", request_path: str = "/v2/accounts", body: str = "") -> str:
        """
        Create ES256-signed JWT (Bearer). Coinbase Advanced typically expects a short-lived JWT.
        """
        if not self.pem_private_key:
            raise RuntimeError("No PEM private key available for JWT generation.")

        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 180,  # 3 minutes
            # some APIs require request_path/method/body in payload — we include them (harmless)
            "method": method.upper(),
            "request_path": request_path,
            "body": body or "",
        }
        try:
            token = jwt.encode(payload, self.pem_private_key, algorithm="ES256")
            # pyjwt returns string on modern versions
            return token
        except Exception as e:
            LOG.error("❌ JWT encoding failed: %s", e)
            raise

    def _request(self, endpoint: str, method: str = "GET", json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Unified request helper. Prefers JWT bearer for auth if configured.
        Raises RuntimeError with informative message on failure.
        """
        url = self.base_url.rstrip("/") + endpoint
        method = method.upper()
        data = None
        if json_body is not None:
            data = json.dumps(json_body)

        headers = {"Content-Type": "application/json"}

        # Choose auth
        if self.auth_mode == "jwt" and self.pem_private_key:
            try:
                token = self._generate_jwt(method=method, request_path=endpoint, body=data or "")
                headers["Authorization"] = f"Bearer {token}"
            except Exception as e:
                raise RuntimeError(f"❌ Failed to build JWT: {e}")
        elif self.auth_mode == "classic" and self.api_key and self.api_secret_raw:
            # Classic mode: we don't implement full exchange HMAC here.
            # Many "classic" flows use CB-ACCESS-KEY/TS/SIGN/PASSPHRASE — if you need this,
            # implement the signing method per Coinbase docs. For now, pass API key in header (best-effort).
            headers["CB-ACCESS-KEY"] = self.api_key
            # Passphrase if present
            if self.passphrase:
                headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
            # NOTE: Without the proper signature you will likely receive 401.
            LOG.warning("⚠️ Classic mode active but full request-signing not implemented. This may cause 401.")
        else:
            LOG.warning("⚠️ No recognized auth mode; attempting unauthenticated request (will likely fail).")

        try:
            resp = requests.request(method, url, headers=headers, data=data, timeout=15)
        except Exception as e:
            raise RuntimeError(f"❌ Network/request error: {e}")

        # Helpful logging for debugging (mask long bodies)
        LOG.debug("HTTP %s %s -> %d", method, endpoint, resp.status_code)

        if resp.status_code == 401:
            # include server message if present
            body_snip = resp.text[:1000]
            raise RuntimeError(f"❌ 401 Unauthorized: {body_snip}")

        if not resp.ok:
            # Provide status + short body
            snippet = resp.text[:1000]
            raise RuntimeError(f"❌ Request failed: {resp.status_code} {snippet}")

        try:
            return resp.json()
        except Exception:
            # Non-JSON but 200 — return raw text in dict
            return {"text": resp.text}

    # -----------------
    # Public API helpers
    # -----------------
    def get_all_accounts(self):
        """
        Returns list of account dicts (same shape as /v2/accounts -> { data: [...] }).
        Normalizes to return the 'data' list or raises informative errors.
        """
        data = self._request("/v2/accounts", "GET")
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        # If not as expected return raw
        return data

    def get_usd_spot_balance(self) -> float:
        """
        Return USD spot balance (float). If not found, returns 0.
        """
        accounts = self.get_all_accounts()
        if not isinstance(accounts, list):
            LOG.warning("⚠️ get_all_accounts returned unexpected shape: %s", type(accounts))
            return 0.0
        for acct in accounts:
            # Coinbase sometimes nests balance under acct['balance']['amount'] and currency under acct['balance']['currency']
            if acct.get("currency") == "USD":
                try:
                    return float(acct.get("balance", {}).get("amount", 0))
                except Exception:
                    pass
            # alternative shape:
            bal = acct.get("balance")
            if isinstance(bal, dict) and bal.get("currency") == "USD":
                try:
                    return float(bal.get("amount", 0))
                except Exception:
                    pass
        return 0.0

    def place_market_order(self, product_id: str = "BTC-USD", side: str = "buy", funds: float = 10.0) -> Dict[str, Any]:
        """
        Create a simple market order using POST /v2/orders (Basic Advanced API). 
        NOTE: This endpoint and required fields may differ by Coinbase product. If your account uses
        a different endpoint (Advanced Trade API), change endpoint & payload accordingly.
        """
        payload = {
            "type": "market",
            "side": side,
            "product_id": product_id,
            # Create order by spending 'funds' USD
            "funds": str(funds)
        }
        LOG.info("👉 Placing market order: %s %s for $%s", side, product_id, funds)
        return self._request("/v2/orders", "POST", json_body=payload)


# -----------------
# Position sizing helper (module-level)
# -----------------
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

    raw_allocation = account_equity * (risk_factor / 100)

    # Clamp allocation between min and max percent
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)

    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size


# -----------------
# Backwards compatible helpers for nija_debug.py and other callers
# -----------------
def get_all_accounts():
    client = CoinbaseClient(preflight=False)
    return client.get_all_accounts()


def get_usd_spot_balance():
    client = CoinbaseClient(preflight=False)
    return client.get_usd_spot_balance()


def place_market_order(product_id="BTC-USD", side="buy", funds=10.0):
    client = CoinbaseClient(preflight=False)
    return client.place_market_order(product_id=product_id, side=side, funds=funds)


# Exported names
__all__ = [
    "CoinbaseClient",
    "calculate_position_size",
    "get_all_accounts",
    "get_usd_spot_balance",
    "place_market_order",
]
