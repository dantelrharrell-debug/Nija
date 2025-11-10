#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import requests
from loguru import logger
import jwt as pyjwt
import random

# -------------------------
# Initialize Nija Client
# -------------------------
class CoinbaseClient:
    def __init__(self):
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

    def _get_headers(self):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "CB-VERSION": "2025-11-09"}
        return {}

    def fetch_accounts(self, retries=3):
        """
        Fetch all Coinbase Advanced account balances with retry/backoff.
        Returns list of account dicts or [] on failure.
        """
        if not self.jwt:
            logger.error("Client inactive — cannot fetch accounts")
            return []

        endpoints = [
            "/api/v3/brokerage/accounts",
            "/accounts",
        ]

        for attempt in range(1, retries + 1):
            for path in endpoints:
                url = self.base.rstrip("/") + path
                try:
                    resp = requests.get(url, headers=self._get_headers(), timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                    for key in ("accounts", "data"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                    if "currency" in data and ("balance" in data or "available" in data):
                        return [data]
                except requests.HTTPError as e:
                    if resp.status_code == 404:
                        logger.warning(f"Endpoint not found (404): {url}, trying next fallback")
                    else:
                        logger.error(f"HTTP error fetching {url}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error fetching {url}: {e}")

            # Exponential backoff before next attempt
            delay = (2 ** attempt) + random.uniform(0, 1)
            logger.info(f"Retrying fetch_accounts in {delay:.2f}s (attempt {attempt}/{retries})")
            time.sleep(delay)

        logger.error("All retries failed — no accounts fetched")
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
        if out.get("USD", 0) <= 0:
            non_zero = {k: v for k, v in out.items() if v > 0}
            if non_zero:
                logger.info(f"USD balance zero — using other currencies: {non_zero}")
            else:
                logger.warning("No non-zero balances found")
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
        if usd_balance > 0:
            logger.info(f"[NIJA-BALANCE] USD: {usd_balance}")
        else:
            for cur, amt in balances.items():
                logger.info(f"[NIJA-BALANCE] {cur}: {amt}")

        # ----> PLACE YOUR TRADING LOGIC HERE <----
        # Example: execute_trade(signal)

        time.sleep(5)
    except Exception as e:
        logger.error(f"Unhandled error in main loop: {e}")
        time.sleep(5)  # slight pause before retrying main loop
