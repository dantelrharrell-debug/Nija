# app/nija_client.py
import os
import time
import json
import random
import logging
import requests
import aiohttp
import pandas as pd
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self):
        self.api_key_id = os.environ.get("COINBASE_API_KEY_ID")
        self.pem_content = os.environ.get("COINBASE_PEM")
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.base_url = "https://api.coinbase.com/api/v3/brokerage"

        if not self.api_key_id or not self.pem_content or not self.org_id:
            raise RuntimeError("Missing Coinbase credentials or org ID!")

        # Load PEM key
        self.private_key = serialization.load_pem_private_key(
            self.pem_content.encode(), password=None, backend=default_backend()
        )
        logger.info("CoinbaseClient initialized with org ID {}", self.org_id)

    # --- JWT generation ---
    def _generate_jwt(self, method="GET", path="/"):
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 300,  # token valid for 5 min
            "sub": self.api_key_id,
            "request_path": path,
            "method": method,
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    # --- Sync account fetch ---
    def get_accounts(self):
        path = f"/organizations/{self.org_id}/accounts"
        url = self.base_url + path
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('GET', path)}",
            "CB-VERSION": "2025-11-12"
        }
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error("HTTP %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()

    # --- Async price fetch ---
    async def fetch_prices(self, symbol):
        path = f"/market_data/{symbol}/candles?granularity=60"
        url = self.base_url + path
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('GET', path)}",
            "CB-VERSION": "2025-11-12"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning(f"Price fetch HTTP {resp.status}: {text}")
                    return []
                data = await resp.json()
                df = pd.DataFrame(data)
                df["close"] = df["close"].astype(float)
                return df["close"].tolist()

    # --- Async order execution ---
    async def execute_order(self, account_id, symbol, side, size):
        path = "/orders"
        url = self.base_url + path
        data = {"side": side, "size": size, "symbol": symbol}
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('POST', path)}",
            "CB-VERSION": "2025-11-12",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=json.dumps(data)) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.warning(f"Order failed HTTP {resp.status}: {text}")
                    return None
                logger.info(f"Order executed: {side.upper()} {symbol} size {size}")
                return await resp.json()

    # --- Async trailing TTP/TSL ---
    async def check_trailing(self, account_id, symbol, prices, trade_state):
        state = trade_state.get(account_id, {}).get(symbol)
        if not state:
            return
        side = state["side"]
        entry = state["entry"]
        ttp = state["ttp"]
        tsl = state["tsl"]
        size = state["size"]
        current_price = prices[-1]

        if side == "buy":
            if current_price > ttp:
                state["ttp"] = current_price * 0.99
            if current_price - entry > 0:
                state["tsl"] = max(tsl, current_price * 0.98)
            if current_price < tsl or current_price < ttp:
                await self.execute_order(account_id, symbol, "sell", size)
                trade_state[account_id].pop(symbol)
                logger.info(f"[{account_id}] {symbol} BUY trade exited.")

        elif side == "sell":
            if current_price < ttp:
                state["ttp"] = current_price * 1.01
            if entry - current_price > 0:
                state["tsl"] = min(tsl, current_price * 1.02)
            if current_price > tsl or current_price > ttp:
                await self.execute_order(account_id, symbol, "buy", size)
                trade_state[account_id].pop(symbol)
                logger.info(f"[{account_id}] {symbol} SELL trade exited.")
