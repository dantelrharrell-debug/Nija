#!/usr/bin/env python3
import os
import time
import json
import asyncio
import logging
import pandas as pd
from nija_hmac_client import CoinbaseClient

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.pro")

# ---------------- Environment Variables ----------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

# ---------------- Symbols to Trade ----------------
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]

# ---------------- Trade State ----------------
TRADE_STATE = {}  # TRADE_STATE[account_id][symbol] = {trade info}

# ---------------- Trading Parameters ----------------
MIN_ALLOCATION = 0.02
MAX_ALLOCATION = 0.10
VOLATILITY_FACTOR = 0.5

# VWAP + RSI parameters
FAST_VWAP_WINDOW = 5
SLOW_VWAP_WINDOW = 20
RSI_PERIOD = 14

# ---------------- Initialize HMAC Client ----------------
client = CoinbaseClient()

# ---------------- Fetch Accounts ----------------
async def get_accounts():
    status, accounts = client.request(method="GET", path="/v2/accounts")
    if status != 200:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return []
    return accounts.get("data", [])

# ---------------- Fetch Historical Prices ----------------
async def fetch_prices(symbol):
    status, resp = client.request(
        method="GET",
        path=f"/market_data/{symbol}/candles?granularity=60"
    )
    if status != 200 or not resp:
        return []
    df = pd.DataFrame(resp)
    df["close"] = df["close"].astype(float)
    return df["close"].tolist()

# ---------------- Indicators ----------------
def compute_vwap(prices):
    return sum(prices) / len(prices)

def compute_fast_slow_vwap(prices):
    fast_vwap = compute_vwap(prices[-FAST_VWAP_WINDOW:]) if len(prices) >= FAST_VWAP_WINDOW else compute_vwap(prices)
    slow_vwap = compute_vwap(prices[-SLOW_VWAP_WINDOW:]) if len(prices) >= SLOW_VWAP_WINDOW else compute_vwap(prices)
    return fast_vwap, slow_vwap

def compute_rsi(prices, period=RSI_PERIOD):
    deltas = pd.Series(prices).diff().dropna()
    gain = deltas.clip(lower=0).rolling(period).mean()
    loss = -deltas.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else 50

def compute_volatility(prices):
    return pd.Series(prices).pct_change().std()

# ---------------- Trade Sizing ----------------
def get_trade_size(balance, allocation, volatility):
    size = balance * allocation * (1 - volatility * VOLATILITY_FACTOR)
    return max(size, 0)

# ---------------- Execute Order ----------------
async def execute_order(account_id, symbol, side, size):
    logger.info(f"[{account_id}] Executing {side.upper()} order for {symbol}, size {size:.4f}")
    data = {"side": side, "size": size, "symbol": symbol}
    status, resp = client.request("POST", "/orders", data)
    if status != 200:
        logger.error(f"❌ Order failed: {resp}")
    return resp

# ---------------- Trailing TTP / TSL ----------------
async def check_trailing(account_id, symbol, prices):
    state = TRADE_STATE.get(account_id, {}).get(symbol)
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
            await execute_order(account_id, symbol, "sell", size)
            TRADE_STATE[account_id].pop(symbol)
            logger.info(f"[{account_id}] {symbol} BUY trade exited.")

    elif side == "sell":
        if current_price < ttp:
            state["ttp"] = current_price * 1.01
        if entry - current_price > 0:
            state["tsl"] = min(tsl, current_price * 1.02)
        if current_price > tsl or current_price > ttp:
            await execute_order(account_id, symbol, "buy", size)
            TRADE_STATE[account_id].pop(symbol)
            logger.info(f"[{account_id}] {symbol} SELL trade exited.")

# ---------------- Trading Logic ----------------
async def trade_account_symbol(account, symbol):
    account_id = account["id"]
    balance = float(account["balance"]["amount"])
    if balance <= 0:
        logger.warning(f"[{account_id}] Account balance zero, skipping {symbol}")
        return

    prices = await fetch_prices(symbol)
    if len(prices) < SLOW_VWAP_WINDOW:
        return

    fast_vwap, slow_vwap = compute_fast_slow_vwap(prices)
    rsi = compute_rsi(prices)
    volatility = compute_volatility(prices)
    allocation = min(MAX_ALLOCATION, max(MIN_ALLOCATION, rsi / 100))
    trade_size = get_trade_size(balance, allocation, volatility)

    if account_id not in TRADE_STATE:
        TRADE_STATE[account_id] = {}

    # VWAP crossover signals
    if fast_vwap > slow_vwap and rsi < 70 and symbol not in TRADE_STATE[account_id]:
        resp = await execute_order(account_id, symbol, "buy", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {"side": "buy", "entry": price, "size": trade_size, "ttp": price*1.01, "tsl": price*0.98}

    elif fast_vwap < slow_vwap and rsi > 30 and symbol not in TRADE_STATE[account_id]:
        resp = await execute_order(account_id, symbol, "sell", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {"side": "sell", "entry": price, "size": trade_size, "ttp": price*0.99, "tsl": price*1.02}

    await check_trailing(account_id, symbol, prices)

# ---------------- Main Loop ----------------
async def main_loop():
    while True:
        accounts = await get_accounts()
        if not accounts:
            logger.warning("No accounts fetched. Check API key permissions.")
            await asyncio.sleep(30)
            continue

        tasks = []
        for account in accounts:
            for symbol in SYMBOLS:
                tasks.append(trade_account_symbol(account, symbol))
        await asyncio.gather(*tasks)
        await asyncio.sleep(60)

# ---------------- Run Bot ----------------
if __name__ == "__main__":
    asyncio.run(main_loop())
