# app/start_bot_main.py
import os
import time
import asyncio
import random
import pandas as pd
from loguru import logger
from nija_client import CoinbaseClient

# --- Trading parameters ---
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]
MIN_ALLOCATION = 0.02
MAX_ALLOCATION = 0.10
VOLATILITY_FACTOR = 0.5

FAST_VWAP_WINDOW = 5
SLOW_VWAP_WINDOW = 20
RSI_PERIOD = 14

# --- Trade state ---
TRADE_STATE = {}  # TRADE_STATE[account_id][symbol] = {trade info}

# --- Helper functions ---
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

def get_trade_size(balance, allocation, volatility):
    size = balance * allocation * (1 - volatility * VOLATILITY_FACTOR)
    return max(size, 0)

# --- Async trading functions ---
async def fetch_prices(client, symbol):
    try:
        resp = client.get_historic_prices(symbol)  # Add method to nija_client for market data
        df = pd.DataFrame(resp)
        df["close"] = df["close"].astype(float)
        return df["close"].tolist()
    except Exception as e:
        logger.warning(f"Failed to fetch prices for {symbol}: {e}")
        return []

async def execute_order(client, account_id, symbol, side, size):
    logger.info(f"[{account_id}] Executing {side.upper()} order for {symbol}, size {size:.4f}")
    try:
        resp = client.place_order(account_id, symbol, side, size)  # Implement place_order in nija_client
        return resp
    except Exception as e:
        logger.error(f"Order failed: {e}")
        return None

async def check_trailing(client, account_id, symbol, prices):
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
            await execute_order(client, account_id, symbol, "sell", size)
            TRADE_STATE[account_id].pop(symbol)
            logger.info(f"[{account_id}] {symbol} BUY trade exited.")

    elif side == "sell":
        if current_price < ttp:
            state["ttp"] = current_price * 1.01
        if entry - current_price > 0:
            state["tsl"] = min(tsl, current_price * 1.02)
        if current_price > tsl or current_price > ttp:
            await execute_order(client, account_id, symbol, "buy", size)
            TRADE_STATE[account_id].pop(symbol)
            logger.info(f"[{account_id}] {symbol} SELL trade exited.")

async def trade_account_symbol(client, account, symbol):
    account_id = account["id"]
    balance = float(account["balance"]["available"])
    if balance <= 0:
        logger.warning(f"[{account_id}] Account balance zero, skipping {symbol}")
        return

    prices = await fetch_prices(client, symbol)
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
        resp = await execute_order(client, account_id, symbol, "buy", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {"side": "buy", "entry": price, "size": trade_size, "ttp": price*1.01, "tsl": price*0.98}

    elif fast_vwap < slow_vwap and rsi > 30 and symbol not in TRADE_STATE[account_id]:
        resp = await execute_order(client, account_id, symbol, "sell", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {"side": "sell", "entry": price, "size": trade_size, "ttp": price*0.99, "tsl": price*1.02}

    await check_trailing(client, account_id, symbol, prices)
    await asyncio.sleep(random.uniform(5, 15))

async def main_loop(client):
    while True:
        try:
            accounts = client.get_accounts().get("data", [])
            if not accounts:
                logger.warning("No accounts fetched. Check API key permissions.")
                await asyncio.sleep(30)
                continue

            tasks = []
            for account in accounts:
                for symbol in SYMBOLS:
                    tasks.append(trade_account_symbol(client, account, symbol))
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            await asyncio.sleep(10)

# --- Run bot ---
if __name__ == "__main__":
    logger.info("Starting Nija Bot (FULL LIVE MODE)...")
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Cannot initialize Coinbase client: %s", e)
        exit(1)

    # Keep container alive with async loop
    try:
        asyncio.run(main_loop(client))
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
