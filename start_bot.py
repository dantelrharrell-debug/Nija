#!/usr/bin/env python3
# start_bot.py
import os
import time
import threading
import random
import requests
from loguru import logger
import jwt as pyjwt  # PyJWT required

# --------- Configuration / Defaults ----------
BASE_ADV_DEFAULT = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com").rstrip("/")
BASE_CLASSIC_DEFAULT = os.getenv("COINBASE_CLASSIC_BASE", "https://api.coinbase.com").rstrip("/")
REFRESH_INTERVAL = int(os.getenv("NIJA_JWT_REFRESH_SECONDS", "240"))  # seconds

# --------- Coinbase Client ----------
class CoinbaseClient:
    def __init__(self, refresh_interval=REFRESH_INTERVAL):
        self.base_advanced = BASE_ADV_DEFAULT
        self.base_classic = BASE_CLASSIC_DEFAULT
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.org_id = os.getenv("COINBASE_ORG_ID") or self.iss
        self.jwt = None
        self.jwt_lock = threading.Lock()
        self.refresh_interval = refresh_interval

        if self.pem and self.iss:
            self._generate_jwt()
            t = threading.Thread(target=self._start_jwt_refresh, daemon=True)
            t.start()
        else:
            logger.warning("COINBASE_PEM_CONTENT or COINBASE_ISS missing -> JWT will not be available")

        logger.info(f"nija_client init: base={self.base_advanced} jwt_set={bool(self.jwt)}")
        print(f"NIJA-CLIENT-READY: base={self.base_advanced} jwt_set={bool(self.jwt)}")

    def _generate_jwt(self):
        try:
            now = int(time.time())
            payload = {"iat": now, "exp": now + 240, "iss": self.iss}
            token = pyjwt.encode(payload, self.pem, algorithm="ES256", headers={"alg": "ES256"})
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            with self.jwt_lock:
                self.jwt = token
            logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
        except Exception as e:
            logger.error(f"Failed to generate JWT from PEM: {e}")
            with self.jwt_lock:
                self.jwt = None

    def _start_jwt_refresh(self):
        while True:
            time.sleep(self.refresh_interval)
            self._generate_jwt()

    def _headers_advanced(self):
        with self.jwt_lock:
            token = self.jwt
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["CB-VERSION"] = "2025-11-09"
        headers["Content-Type"] = "application/json"
        if self.org_id:
            headers["CB-ACCESS-ORG"] = self.org_id
        return headers

    def _headers_classic(self):
        # Placeholder; for real HMAC you must construct CB-ACCESS-SIGN properly.
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["CB-ACCESS-KEY"] = self.api_key
        if self.api_secret:
            headers["CB-ACCESS-SIGN"] = self.api_secret
        headers["CB-ACCESS-TIMESTAMP"] = str(int(time.time()))
        return headers

    def _fetch_advanced_accounts(self):
        path = "/api/v3/brokerage/accounts"
        url = self.base_advanced + path
        try:
            resp = requests.get(url, headers=self._headers_advanced(), timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                for k in ("accounts", "data"):
                    if k in data and isinstance(data[k], list):
                        return data[k]
                if isinstance(data, list):
                    return data
                return []
            else:
                logger.warning(f"Advanced API returned {resp.status_code} for {url}")
                logger.debug("ADV body: %s", resp.text[:600])
                return None
        except requests.RequestException as e:
            logger.error(f"Advanced API request exception: {e}")
            return None
        except Exception as e:
            logger.error(f"Advanced API unexpected exception: {e}")
            return None

    def _fetch_accounts_fallback(self):
        # second attempt general `/accounts` on same base (some deployments)
        path = "/accounts"
        url = self.base_advanced + path
        try:
            resp = requests.get(url, headers=self._headers_advanced(), timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                # normalize
                if isinstance(data, dict):
                    for k in ("data", "accounts"):
                        if k in data and isinstance(data[k], list):
                            return data[k]
                if isinstance(data, list):
                    return data
                return []
            else:
                logger.warning(f"Fallback advanced '/accounts' returned {resp.status_code} for {url}")
                logger.debug("FB body: %s", resp.text[:600])
                return None
        except Exception as e:
            logger.error(f"Fallback advanced request exception: {e}")
            return None

    def _fetch_classic_accounts(self):
        url = self.base_classic + "/v2/accounts"
        try:
            resp = requests.get(url, headers=self._headers_classic(), timeout=12)
            if resp.status_code == 200:
                return resp.json().get("data", [])
            else:
                logger.warning(f"Classic API returned {resp.status_code} for {url}")
                logger.debug("CLASSIC body: %s", resp.text[:600])
                return None
        except Exception as e:
            logger.error(f"Classic API exception: {e}")
            return None

    def fetch_accounts(self, retries=3):
        # Try advanced if JWT exists
        if self.jwt:
            adv = self._fetch_advanced_accounts()
            if isinstance(adv, list):
                return adv
            # try fallback advanced '/accounts' once
            fb = self._fetch_accounts_fallback()
            if isinstance(fb, list):
                return fb

        # Try classic fallback (if keys present)
        if self.api_key and self.api_secret:
            for attempt in range(retries):
                classic = self._fetch_classic_accounts()
                if isinstance(classic, list):
                    return classic
                backoff = (2 ** attempt) + random.uniform(0, 0.5)
                logger.info(f"Classic fallback sleeping {backoff:.2f}s before retry ({attempt+1}/{retries})")
                time.sleep(backoff)

        logger.error("No accounts fetched — both Advanced and Classic failed/tried")
        return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        out = {}
        if not accounts:
            return out
        for a in accounts:
            try:
                # try common shapes
                if isinstance(a.get("balance"), dict):
                    amount = a["balance"].get("amount") or a["balance"].get("value") or 0
                    currency = a["balance"].get("currency") or a.get("currency") or a.get("asset")
                else:
                    amount = a.get("available_balance") or a.get("available") or a.get("balance") or 0
                    currency = a.get("currency") or a.get("asset")
                # normalize strings with commas
                if isinstance(amount, str):
                    amount = amount.replace(",", "")
                out[currency] = float(amount or 0)
            except Exception:
                continue
        return out

# Alias
NijaCoinbaseClient = CoinbaseClient

# --------- Main loop ----------
if __name__ == "__main__":
    logger.info("Starting Nija bot — LIVE mode")
    client = NijaCoinbaseClient()

    # initial one-shot debug print
    balances = client.get_balances()
    if not balances:
        logger.warning("[NIJA-BALANCE] No balances returned (check service key scopes, COINBASE_BASE, COINBASE_ISS)")
    else:
        for k, v in balances.items():
            logger.info(f"[NIJA-BALANCE] {k}: {v}")

    try:
        while True:
            try:
                balances = client.get_balances()
                usd = balances.get("USD", 0)
                if usd > 0:
                    logger.info(f"[NIJA-BALANCE] USD: {usd}")
                else:
                    if balances:
                        for cur, amt in balances.items():
                            logger.info(f"[NIJA-BALANCE] {cur}: {amt}")
                    else:
                        logger.info("[NIJA-BALANCE] no balances returned this tick")
                # place trading logic here
                time.sleep(5)
            except Exception as e:
                logger.error("Unhandled error in main loop: %s", e)
                time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Nija bot stopped by user")
