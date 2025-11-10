#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import requests
from loguru import logger
import jwt as pyjwt

# -------------------------
# Initialize Nija Client
# -------------------------
class CoinbaseClient:
    def __init__(self):
        # Base URL from env
        self.base = os.getenv("COINBASE_BASE", "https://api.coinbase.com")
        self.jwt = None
        self._init_jwt()
        logger.info(f"nija_client init: base={self.base} advanced=True jwt_set={bool(self.jwt)}")
        print(f"NIJA-CLIENT-READY: base={self.base} jwt_set={bool(self.jwt)}")

    def _init_jwt(self):
        pem = os.getenv("COINBASE_PEM_CONTENT")
        iss = os.getenv("COINBASE_ISS")
        if pem and iss:
            try:
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300, "iss": iss}
                token = pyjwt.encode(payload, pem, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                logger.error(f"Failed to generate JWT: {e}")
        else:
            logger.warning("COINBASE_PEM_CONTENT or COINBASE_ISS missing")

    def fetch_accounts(self):
        """
        Fetch all Coinbase Advanced account balances.
        Returns list of account dicts or [] on failure.
        """
        if not self.jwt:
            logger.error("Client inactive — cannot fetch accounts")
            return []

        url = f"{self.base}/api/v3/brokerage/accounts"
        headers = {"Authorization": f"Bearer {self.jwt}", "CB-VERSION": "2025-11-09"}

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # v3 returns {"accounts": [...]} or {"data": [...]}
            for key in ("accounts", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            # single account dict fallback
            if "currency" in data and ("balance" in data or "available" in data):
                return [data]
            return []
        except requests.HTTPError as e:
            logger.error(f"API endpoint error (HTTP): {e} | status={getattr(resp, 'status_code', None)} | url={url}")
        except Exception as e:
            logger.error(f"Unexpected error fetching accounts: {e}")
        return []

    def get_balances(self):
        """
        Returns dict: {currency: balance}
        """
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

# Alias
NijaCoinbaseClient = CoinbaseClient

# -------------------------
# Start Live Bot
# -------------------------
logger.info("Starting Nija bot — LIVE mode")
client = NijaCoinbaseClient()

while True:
    try:
        balances = client.get_balances()
        usd_balance = balances.get("USD", 0)
        logger.info(f"[NIJA-BALANCE] USD: {usd_balance}")

        # ----> PLACE YOUR TRADING LOGIC HERE <----
        # Example: execute_trade(signal)

        time.sleep(5)  # poll every 5 seconds
    except Exception as e:
        logger.error(f"Unhandled error in main loop: {e}")
