# nija_client.py
import os
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.jwt_set = False
        self.api_key_set = bool(os.getenv("COINBASE_ISS"))
        self._init_jwt()
        logger.info(f"nija_client init: base= {self.base} advanced= True jwt_set= {self.jwt_set}")

    def _init_jwt(self):
        pem_content = os.getenv("COINBASE_PEM_CONTENT")
        if pem_content:
            try:
                # Example: generate ephemeral JWT from PEM
                # Replace with your actual JWT generation if needed
                self.jwt_set = True
                logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                logger.warning(f"Failed to generate JWT from PEM: {e}")
        else:
            logger.warning("No COINBASE_PEM_CONTENT provided")

    def get_accounts(self):
        if not self.jwt_set:
            logger.error("Advanced mode requires JWT (COINBASE_JWT or valid COINBASE_PEM_CONTENT). Returning [].")
            return []

        url = f"{self.base}/accounts"  # ✅ Correct endpoint
        try:
            headers = {
                "Authorization": f"Bearer {os.getenv('COINBASE_JWT','')}",
                "CB-VERSION": "2025-11-09",
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            accounts = response.json()
            return accounts
        except requests.HTTPError as e:
            logger.error(f"Error fetching accounts: {e}")
            return []

# Example usage
if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.get_accounts()
    for acc in accounts:
        logger.info(f"[NIJA-ACCOUNT] {acc['currency']}: {acc['balance']}")

# nija_client.py  (PROJECT ROOT) - Advanced/Pro-aware client (JWT required for Advanced/v3)
"""
Robust Coinbase client:
- Uses Advanced Trade v3 endpoint when advanced_mode=True: GET /api/v3/brokerage/accounts (requires Bearer JWT)
- Uses Exchange/Pro base when advanced_mode=False: GET /accounts (HMAC or JWT)
- Defensive: if Advanced mode & no JWT -> logs helpful error and returns []
- Exposes CoinbaseClient and alias NijaCoinbaseClient
"""

import os, time, base64, hmac, hashlib

# lazy import requests
try:
    import requests
    REQUESTS = True
except Exception:
    requests = None
    REQUESTS = False

def _log(level, *parts):
    try:
        from loguru import logger as _lg
        getattr(_lg, level)(" ".join(map(str, parts)))
    except Exception:
        print(f"[{level.upper()}]", *parts)

class CoinbaseClient:
    def __init__(self,
                 api_key=None,
                 api_secret=None,
                 passphrase=None,
                 org_id=None,
                 base=None,
                 advanced_mode: bool = None):
        # env-backed config
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID") or os.getenv("COINBASE_ISS")
        self.custom_base = (base or os.getenv("COINBASE_BASE", "")).strip() or None

        # detect mode
        if advanced_mode is not None:
            self.advanced_mode = bool(advanced_mode)
        else:
            m = os.getenv("COINBASE_AUTH_MODE", "").lower()
            if m in ("advanced", "cdp", "jwt"):
                self.advanced_mode = True
            elif m in ("pro", "exchange", "hmac"):
                self.advanced_mode = False
            else:
                # default: advanced if org id or PEM present
                self.advanced_mode = bool(self.org_id or os.getenv("COINBASE_PEM_CONTENT"))

        # choose base:
        if self.custom_base:
            self.base = self.custom_base.rstrip("/")
        else:
            # For Advanced (modern) use api.coinbase.com/api/v3/brokerage/...
            # For Pro/Exchange use api.exchange.coinbase.com
            self.base = "https://api.coinbase.com" if self.advanced_mode else "https://api.exchange.coinbase.com"

        # JWT: direct env or attempt PEM -> jwt (only if pyjwt available)
        self.jwt = os.getenv("COINBASE_JWT") or None
        pem = os.getenv("COINBASE_PEM_CONTENT")
        if not self.jwt and pem:
            try:
                # Try to form a minimal ES256 JWT (best-effort). If pyjwt not available, skip.
                import jwt as _pyjwt
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300}
                iss = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ORG_ID")
                if iss:
                    payload["iss"] = iss
                # pyjwt may accept PEM string directly for ES256 if key correct
                token = _pyjwt.encode(payload, pem, algorithm="ES256", headers={"alg":"ES256"})
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                _log("info", "Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                _log("warning", "Failed to generate JWT from PEM:", e)
                self.jwt = None

        _log("info", "nija_client init: base=", self.base, "advanced=", self.advanced_mode, "jwt_set=", bool(self.jwt))

        try:
            print("NIJA-CLIENT-READY: CoinbaseClient (base=%s advanced=%s jwt=%s)" %
                  (self.base, self.advanced_mode, bool(self.jwt)))
        except Exception:
            pass

    # Helpers
    def _decode_secret(self, s):
        if not s:
            return b""
        try:
            return base64.b64decode(s)
        except Exception:
            return s.encode("utf-8")

    def _hmac_sig(self, ts, method, path, body=""):
        msg = ts + method.upper() + path + (body or "")
        key = self._decode_secret(self.api_secret or "")
        sig = hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(sig).decode("utf-8")

    def _headers_for(self, method, path, body=""):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        # HMAC fallback (only used for Exchange/Pro style)
        ts = str(int(time.time()))
        sig = self._hmac_sig(ts, method, path, body)
        h = {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        if self.passphrase:
            h["CB-ACCESS-PASSPHRASE"] = self.passphrase
        # add org header for advanced when provided (some CDP keys require it)
        if self.advanced_mode and (self.org_id):
            h["CB-ACCESS-ORG"] = self.org_id
        return h

    def fetch_accounts(self):
        """
        Advanced mode:
          GET https://api.coinbase.com/api/v3/brokerage/accounts  (JWT Bearer required)
        Exchange/Pro mode:
          GET https://api.exchange.coinbase.com/accounts (HMAC or JWT)
        Returns list of account dicts or [] on failure.
        """
        if self.advanced_mode:
            # require JWT for Advanced endpoints; if missing, log and return empty to avoid 404 loops
            if not self.jwt:
                _log("error", "Advanced mode requires JWT (COINBASE_JWT or valid COINBASE_PEM_CONTENT). Returning [].")
                _log("error", "See docs: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api and create a Service Key or set COINBASE_JWT.")
                return []
            path = "/api/v3/brokerage/accounts"
            url = self.base.rstrip("/") + path
            headers = self._headers_for("GET", path, "")
        else:
            path = "/accounts"
            url = self.base.rstrip("/") + path
            headers = self._headers_for("GET", path, "")

        if not REQUESTS:
            _log("error", "requests not available; fetch_accounts returning []")
            return []

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # normalize shapes:
            if isinstance(data, dict):
                # v3 brokerage returns {"accounts": [...] } or {"data": [...]}
                for key in ("accounts", "data"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # single account dict?
                if "currency" in data and ("balance" in data or "available" in data):
                    return [data]
                return []
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            try:
                _log("error", "Error fetching accounts:", e, "status=", getattr(resp, "status_code", None), "url=", url,
                     "body_trunc=", getattr(resp, "text", "")[:800])
            except Exception:
                _log("error", "Error fetching accounts:", e, "url=", url)
            return []

    # Aliases
    def get_accounts(self):
        return self.fetch_accounts()

    def list_accounts(self):
        return self.fetch_accounts()

    def get_account_balances(self):
        accs = self.fetch_accounts()
        out = {}
        for a in accs:
            cur = a.get("currency") or a.get("asset")
            amt = None
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                out[cur] = float(amt or 0)
            except Exception:
                try:
                    out[cur] = float(str(amt).replace(",",""))
                except Exception:
                    out[cur] = 0.0
        return out

    def get_balances(self):
        return self.get_account_balances()

# alias for older code
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
