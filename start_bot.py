#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import threading
import requests
from loguru import logger
import jwt as pyjwt  # Ensure PyJWT is installed

logger.info("Starting Nija bot — LIVE mode")

# -------------------------
# Coinbase Advanced Client
# -------------------------
class CoinbaseClient:
    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.coinbase.com")
        self.jwt = None
        self.active = False
        self._init_jwt()
        # Start background thread to refresh JWT
        threading.Thread(target=self._refresh_jwt_loop, daemon=True).start()
        logger.info(f"Client initialized: base={self.base} jwt_set={bool(self.jwt)}")
        print(f"NIJA-CLIENT-READY: base={self.base} jwt_set={bool(self.jwt)}")

    def _init_jwt(self):
        pem = os.getenv("COINBASE_PEM_CONTENT")
        iss = os.getenv("COINBASE_ISS")
        if pem and iss:
            try:
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300, "iss": iss}  # 5 min expiry
                token = pyjwt.encode(payload, pem, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                self.active = True
                logger.info("Generated ephemeral JWT from PEM")
            except Exception as e:
                logger.error(f"Failed to generate JWT: {e}")
                self.active = False
        else:
            logger.error("Missing COINBASE_PEM_CONTENT or COINBASE_ISS")
            self.active = False

    def _refresh_jwt_loop(self):
        """Refresh JWT every 4 minutes to avoid expiration"""
        while True:
            time.sleep(240)  # 4 minutes
            try:
                self._init_jwt()
                logger.info("JWT refreshed automatically")
            except Exception as e:
                logger.error(f"Error refreshing JWT: {e}")
                self.active = False

    def fetch_accounts(self):
        if not self.active:
            logger.warning("Client inactive — cannot fetch accounts")
            return []

        url = f"{self.base}/api/v3/brokerage/accounts"
        headers = {"Authorization": f"Bearer {self.jwt}", "CB-VERSION": "2025-11-09"}

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 404:
                logger.error("API endpoint not found (404). Check your base URL and service key.")
                self.active = False
                return []
            resp.raise_for_status()
            data = resp.json()
            for key in ("accounts", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            if "currency" in data and ("balance" in data or "available" in data):
                return [data]
            return []
        except requests.HTTPError as e:
            logger.error(f"HTTPError fetching accounts: {e} | status={getattr(resp,'status_code', None)}")
            self.active = False
        except Exception as e:
            logger.error(f"Unexpected error fetching accounts: {e}")
            self.active = False
        return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        out = {}
        for a in accounts:
            cur = a.get("currency") or a.get("asset")
            amt = a.get("available_balance") or a.get("balance") or 0
            try:
                out[cur] = float(amt)
            except Exception:
                out[cur] = 0.0
        return out


# -------------------------
# Initialize client
# -------------------------
client = CoinbaseClient()
if not client.active:
    logger.error("Bot cannot start — JWT or API misconfigured. Exiting.")
    exit(1)

# -------------------------
# Main live loop
# -------------------------
while True:
    try:
        balances = client.get_balances()
        usd = balances.get("USD", 0)
        logger.info(f"[NIJA-BALANCE] USD: {usd}")

        # ----> PLACE YOUR TRADING LOGIC HERE <----
        # Example: execute_trade(signal)

        time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Bot stopped manually")
        break
    except Exception as e:
        logger.error(f"Unhandled error in live loop: {e}")
        time.sleep(5)
