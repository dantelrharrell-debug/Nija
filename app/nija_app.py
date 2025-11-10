# app/nija_client.py
#!/usr/bin/env python3
import os
import time
import threading
import requests
from loguru import logger
import jwt as pyjwt  # PyJWT must be installed

# Environment variables expected:
# COINBASE_PEM_CONTENT  -> multiline PEM string (-----BEGIN EC PRIVATE KEY----- ... -----END EC PRIVATE KEY-----)
# COINBASE_ISS          -> the service key issuer (iss)
# COINBASE_BASE         -> optional override; default set below for Advanced/CDP
# COINBASE_API_KEY / COINBASE_API_SECRET -> optional classic API fallback

BASE_ADV_DEFAULT = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")  # typical CDP base
BASE_CLASSIC_DEFAULT = os.getenv("COINBASE_CLASSIC_BASE", "https://api.coinbase.com")  # classic

class CoinbaseClient:
    def __init__(self):
        self.base_advanced = BASE_ADV_DEFAULT.rstrip('/')
        self.base_classic = BASE_CLASSIC_DEFAULT.rstrip('/')
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.jwt = None
        # generate ephemeral JWT if possible
        if self.pem and self.iss:
            self._generate_jwt()
            # refresh thread
            t = threading.Thread(target=self._start_jwt_refresh, daemon=True)
            t.start()
        else:
            logger.warning("COINBASE_PEM_CONTENT or COINBASE_ISS missing (no JWT).")

        logger.info("nija_client init: base=%s advanced=%s jwt_set=%s" % (self.base_advanced, True, bool(self.jwt)))
        print("NIJA-CLIENT-READY: base=%s jwt_set=%s" % (self.base_advanced, bool(self.jwt)))

    def _generate_jwt(self):
        try:
            now = int(time.time())
            payload = {"iat": now, "exp": now + 240, "iss": self.iss}
            token = pyjwt.encode(payload, self.pem, algorithm="ES256", headers={"alg":"ES256"})
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt = token
            logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
        except Exception as e:
            logger.error("Failed to generate JWT from PEM: %s" % (e,))
            self.jwt = None

    def _start_jwt_refresh(self):
        # Refresh token every 4 minutes (shorter than exp)
        while True:
            time.sleep(240)
            self._generate_jwt()

    def _headers_advanced(self):
        h = {"Authorization": f"Bearer {self.jwt}", "CB-VERSION": "2025-11-09", "Content-Type": "application/json"}
        # If your service key requires an org header, include it:
        org = os.getenv("COINBASE_ORG_ID") or os.getenv("COINBASE_ISS")
        if org:
            h["CB-ACCESS-ORG"] = org
        return h

    def _headers_classic(self):
        # NOTE: This is a simplified placeholder. For production HMAC you must construct CB-ACCESS-SIGN properly.
        h = {"CB-ACCESS-KEY": self.api_key or "", "CB-ACCESS-SIGN": self.api_secret or "", "CB-ACCESS-TIMESTAMP": str(int(time.time())), "Content-Type": "application/json"}
        return h

    def _fetch_advanced_accounts(self):
        # Advanced / CDP brokerage endpoint
        path = "/api/v3/brokerage/accounts"
        url = self.base_advanced + path
        try:
            resp = requests.get(url, headers=self._headers_advanced(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # normalize v3 shapes
                for k in ("accounts","data"):
                    if k in data and isinstance(data[k], list):
                        return data[k]
                # if top-level list
                if isinstance(data, list):
                    return data
                return []
            else:
                logger.warning("Advanced API returned %s for %s" % (resp.status_code, url))
                # include body for debugging (short)
                logger.debug("ADV body: %s" % (resp.text[:500],))
                return None  # None means tried but didn't succeed
        except Exception as e:
            logger.error("Advanced API exception: %s" % (e,))
            return None

    def _fetch_classic_accounts(self):
        # Classic endpoint (v2)
        url = self.base_classic + "/v2/accounts"
        try:
            resp = requests.get(url, headers=self._headers_classic(), timeout=10)
            if resp.status_code == 200:
                return resp.json().get("data", [])
            else:
                logger.warning("Classic API returned %s for %s" % (resp.status_code, url))
                logger.debug("CLASSIC body: %s" % (resp.text[:500],))
                return None
        except Exception as e:
            logger.error("Classic API exception: %s" % (e,))
            return None

    def fetch_accounts(self):
        # 1) Try Advanced (only if jwt present)
        if self.jwt:
            adv = self._fetch_advanced_accounts()
            if adv is None:
                # advanced attempted but failed with non-404/non-empty shape -> continue to fallback
                pass
            elif isinstance(adv, list) and adv:
                return adv
            # if adv == [] it mean endpoint returned 200 but no accounts; return that
            if adv == []:
                return []

        # 2) Try classic fallback (if API key/secret exist)
        if self.api_key and self.api_secret:
            classic = self._fetch_classic_accounts()
            if isinstance(classic, list):
                return classic

        # nothing available
        logger.error("No accounts fetched — both Advanced and Classic failed/tried")
        return []

    def get_balances(self):
        accs = self.fetch_accounts()
        out = {}
        if not accs:
            return out
        # handle both list of accounts and dict shapes
        for a in accs:
            # many shapes exist; try common fields:
            try:
                # v3 shape: account['balance'] might be {'amount': '1.23','currency':'USD'}
                bal = None
                cur = None
                if isinstance(a.get("balance"), dict):
                    bal = a["balance"].get("amount") or a["balance"].get("value")
                    cur = a["balance"].get("currency") or a.get("currency") or a.get("asset")
                else:
                    bal = a.get("available_balance") or a.get("available") or a.get("balance")
                    cur = a.get("currency") or a.get("asset")
                if cur:
                    out[cur] = float(str(bal or 0).replace(",",""))
            except Exception:
                continue
        return out

# Export alias
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
