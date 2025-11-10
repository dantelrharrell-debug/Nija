# app/nija_client.py
import os
import time
import hmac
import hashlib
import base64
import threading
import requests
from loguru import logger

try:
    import jwt as pyjwt
except Exception:
    pyjwt = None

logger.add(lambda r: print(r, end=""))  # ensure logs show in container output

class CoinbaseClient:
    """
    Robust client that:
    - Generates ephemeral ES256 JWT from COINBASE_PEM_CONTENT + COINBASE_ISS for Advanced API
    - Tries Advanced endpoints first (with COINBASE_BASE override)
    - Falls back to Classic API using correct HMAC signature
    """

    def __init__(self, jwt_refresh_secs: int = 240):
        # env-backed configuration
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ORG_ID")
        self.org_id = os.getenv("COINBASE_ORG_ID") or os.getenv("COINBASE_ISS")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Accept platform override; default prefer api.coinbase.com for service keys
        self.base = os.getenv("COINBASE_BASE", "").rstrip("/") or "https://api.cdp.coinbase.com"
        # We'll try both canonical candidates if needed:
        self.candidate_bases = [self.base]
        if "cdp.coinbase.com" in self.base and "api.coinbase.com" not in self.base:
            self.candidate_bases.insert(0, "https://api.coinbase.com")
        elif "api.coinbase.com" in self.base and "https://api.cdp.coinbase.com" not in self.base:
            self.candidate_bases.append("https://api.cdp.coinbase.com")

        self.jwt = None
        self.jwt_lock = threading.Lock()
        self.jwt_refresh_secs = int(os.getenv("NIJA_JWT_REFRESH_SECONDS", jwt_refresh_secs))

        if self.pem and self.iss and pyjwt:
            self._generate_jwt()
            self._start_jwt_refresh()
        else:
            if not self.pem or not self.iss:
                logger.warning("COINBASE_PEM_CONTENT or COINBASE_ISS missing — advanced JWT disabled")
            if not pyjwt:
                logger.warning("PyJWT not installed — cannot generate ES256 JWT for advanced API")

        logger.info(f"nija_client init: base={self.base} jwt_set={bool(self.jwt)}")

    # -------------------
    # JWT (Advanced) helpers
    # -------------------
    def _generate_jwt(self):
        try:
            now = int(time.time())
            payload = {"iat": now, "exp": now + 300, "iss": self.iss}
            token = pyjwt.encode(payload, self.pem, algorithm="ES256", headers={"alg": "ES256"})
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            with self.jwt_lock:
                self.jwt = token
            logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
        except Exception as e:
            logger.error("Failed to generate JWT: %s" % e)
            with self.jwt_lock:
                self.jwt = None

    def _start_jwt_refresh(self):
        def loop():
            while True:
                time.sleep(self.jwt_refresh_secs)
                self._generate_jwt()
        threading.Thread(target=loop, daemon=True).start()
        logger.info(f"JWT auto-refresh started: every {self.jwt_refresh_secs} seconds")

    def _advanced_headers(self):
        with self.jwt_lock:
            token = self.jwt
        h = {"Authorization": f"Bearer {token}"} if token else {}
        h["CB-VERSION"] = "2025-11-09"
        h["Content-Type"] = "application/json"
        if self.org_id:
            h["CB-ACCESS-ORG"] = self.org_id
        return h

    # -------------------
    # Classic HMAC signing helper
    # -------------------
    def _classic_headers(self, method: str, path: str, body: str = ""):
        """
        Proper Coinbase classic signature:
        timestamp + method + path + body, HMAC-SHA256 with api_secret (bytes), base64 encoded.
        """
        ts = str(int(time.time()))
        method_up = method.upper()
        preimage = ts + method_up + path + (body or "")
        key = (self.api_secret or "").encode("utf-8")
        sig = base64.b64encode(hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
        headers = {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        if passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = passphrase
        return headers

    # -------------------
    # Fetching accounts (tries advanced then classic)
    # -------------------
    def _fetch_advanced_accounts(self, base_candidate: str):
        """
        Attempt to fetch accounts from advanced endpoints on the provided base.
        Returns (accounts_list or None) — None means endpoint unreachable/404/unauth.
        """
        if not self.jwt:
            logger.debug("No JWT; skipping advanced on %s" % base_candidate)
            return None
        endpoints = ["/api/v3/brokerage/accounts", "/accounts"]
        for path in endpoints:
            url = base_candidate.rstrip("/") + path
            try:
                resp = requests.get(url, headers=self._advanced_headers(), timeout=12)
                if resp.status_code == 200:
                    logger.info(f"Advanced API success at {url}")
                    # normalize possible shapes
                    data = resp.json()
                    for key in ("accounts", "data"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                    # maybe a single account dict
                    if isinstance(data, dict) and ("currency" in data or "asset" in data):
                        return [data]
                    return []
                elif resp.status_code in (401, 403):
                    logger.warning(f"Advanced API auth error {resp.status_code} at {url}: {resp.text[:400]}")
                    return None
                elif resp.status_code == 404:
                    logger.warning(f"Advanced API returned 404 for {url}")
                    # try next path or base
                else:
                    logger.warning(f"Advanced API returned {resp.status_code} for {url}: {resp.text[:400]}")
            except requests.RequestException as e:
                logger.warning(f"Advanced API request exception for {url}: {e}")
        return None

    def _fetch_classic_accounts(self):
        """
        Fetch via classic (v2) endpoint using HMAC signing. Returns list or None on auth failure.
        """
        if not (self.api_key and self.api_secret):
            logger.debug("Classic API keys not present; skipping classic fallback")
            return None
        path = "/v2/accounts"
        url = "https://api.coinbase.com" + path
        try:
            headers = self._classic_headers("GET", path, "")
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                logger.info("Classic API success")
                return resp.json().get("data", [])
            elif resp.status_code == 401:
                logger.warning("Classic API returned 401 (auth failed). Check API key/secret and signature.")
                logger.debug("CLASSIC body: %s" % resp.text[:800])
                return None
            else:
                logger.warning(f"Classic API returned {resp.status_code}: {resp.text[:400]}")
                return None
        except requests.RequestException as e:
            logger.warning("Classic API request exception: %s" % e)
            return None

    def fetch_accounts(self, retries: int = 3):
        """
        Top-level: try advanced on candidate bases, then classic fallback.
        Returns accounts list (possibly empty) or [] on complete failure.
        """
        # Try advanced across candidate bases
        for base_candidate in self.candidate_bases:
            adv_res = self._fetch_advanced_accounts(base_candidate)
            if adv_res is None:
                # None => endpoint existed but auth failed OR network error occurred
                # We will continue to try other base candidates
                continue
            # adv_res is list (could be empty) -> return it (even empty is valid)
            return adv_res

        # advanced did not return usable data; try classic with retries/backoff
        if self.api_key and self.api_secret:
            for attempt in range(1, retries + 1):
                res = self._fetch_classic_accounts()
                if res is None:
                    # auth failure or exception; backoff then retry
                    delay = (2 ** attempt) * 0.5
                    logger.info("Classic fallback sleeping %.2fs before retry (%d/%d)" % (delay, attempt, retries))
                    time.sleep(delay)
                    continue
                return res

        logger.error("No accounts fetched — both Advanced and Classic failed/tried")
        return []

    def get_balances(self):
        """
        Returns dict mapping currency -> float balance
        """
        accounts = self.fetch_accounts()
        out = {}
        if not accounts:
            return out
        for a in accounts:
            # normalize common shapes
            cur = a.get("currency") or (a.get("balance") or {}).get("currency") or a.get("asset")
            amt = None
            bal = a.get("balance") or a.get("available_balance") or a.get("available")
            if isinstance(bal, dict):
                amt = bal.get("amount") or bal.get("value")
            else:
                amt = bal
            try:
                out[cur] = float(amt or 0)
            except Exception:
                try:
                    out[cur] = float(str(amt).replace(",", ""))
                except Exception:
                    out[cur] = 0.0
        return out

# alias
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
