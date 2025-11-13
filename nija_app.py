# nija_app.py
import os
import sys
import asyncio
import random
import pandas as pd
import logging
from loguru import logger
from nija_client import CoinbaseClient

# Ensure logs flush immediately (Railway-friendly)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# --- Config ---
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]
MIN_POSITION = 0.02
MAX_POSITION = 0.10
VOLATILITY_FACTOR = 0.5

FAST_VWAP_WINDOW = 5
SLOW_VWAP_WINDOW = 20
RSI_PERIOD = 14

TRADE_STATE = {}  # TRADE_STATE[account_id][symbol] = {trade info}

# --- Indicator helpers ---
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

# --- Placeholder for API request helpers ---
async def fetch_prices(client, symbol):
    """Fetch last 60 1-minute candles for the symbol"""
    try:
        resp = client.get_candles(symbol, granularity=60)  # implement get_candles in nija_client if missing
        df = pd.DataFrame(resp)
        df["close"] = df["close"].astype(float)
        return df["close"].tolist()
    except Exception as e:
        logger.warning("Failed to fetch prices for %s: %s", symbol, e)
        return []

async def execute_order(client, account_id, symbol, side, size):
    """Place order via Coinbase client"""
    logger.info("[%s] Executing %s order for %s size %.6f", account_id, side.upper(), symbol, size)
    try:
        resp = client.place_order(account_id, symbol, side, size)  # implement place_order in nija_client
        return resp
    except Exception as e:
        logger.error("[%s] Order failed: %s", account_id, e)
        return None

async def check_trailing(account_id, symbol, prices, client):
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
            logger.info("[%s] BUY trade exited for %s", account_id, symbol)

    elif side == "sell":
        if current_price < ttp:
            state["ttp"] = current_price * 1.01
        if entry - current_price > 0:
            state["tsl"] = min(tsl, current_price * 1.02)
        if current_price > tsl or current_price > ttp:
            await execute_order(client, account_id, symbol, "buy", size)
            TRADE_STATE[account_id].pop(symbol)
            logger.info("[%s] SELL trade exited for %s", account_id, symbol)

async def trade_account_symbol(client, account, symbol):
    account_id = account["id"]
    balance = float(account["balance"]["available"])
    if balance <= 0:
        logger.warning("[%s] Zero balance, skipping %s", account_id, symbol)
        return

    prices = await fetch_prices(client, symbol)
    if len(prices) < SLOW_VWAP_WINDOW:
        return

    fast_vwap, slow_vwap = compute_fast_slow_vwap(prices)
    rsi = compute_rsi(prices)
    volatility = compute_volatility(prices)
    allocation = min(MAX_POSITION, max(MIN_POSITION, rsi / 100))
    trade_size = get_trade_size(balance, allocation, volatility)

    if account_id not in TRADE_STATE:
        TRADE_STATE[account_id] = {}

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

    await check_trailing(account_id, symbol, prices, client)
    await asyncio.sleep(random.uniform(5, 15))  # prevent rate limits

async def live_trading_loop(client):
    while True:
        try:
            accounts_resp = client.get_accounts()
            accounts = accounts_resp.get("data") if isinstance(accounts_resp, dict) else []
            if not accounts:
                logger.warning("❌ No accounts fetched. Check API key permissions.")
            else:
                tasks = []
                for account in accounts:
                    for symbol in SYMBOLS:
                        tasks.append(trade_account_symbol(client, account, symbol))
                await asyncio.gather(*tasks)
        except Exception as e:
            logger.error("Live loop error: %s", e)
        await asyncio.sleep(10)  # loop delay

async def keep_alive():
    while True:
        await asyncio.sleep(60)

async def main():
    logger.info("Starting Nija Bot (VWAP+RSI live)...")
    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error("Cannot initialize Coinbase client: %s", e)
        return

    await asyncio.gather(
        live_trading_loop(client),
        keep_alive()
    )

if __name__ == "__main__":
    asyncio.run(main())
