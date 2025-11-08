#!/usr/bin/env python3
import os
import tempfile
import logging
import asyncio
import time
import requests
from nija_coinbase_jwt_client import CoinbaseJWTClient

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.dynamic")

# ---------------------------
# PEM setup
# ---------------------------
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if not pem_content:
    raise ValueError("COINBASE_PEM_CONTENT not set in .env")

temp_pem = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
temp_pem.write(pem_content.encode())
temp_pem.flush()
os.environ["COINBASE_PRIVATE_KEY_PATH"] = temp_pem.name

# ---------------------------
# Initialize client
# ---------------------------
client = CoinbaseJWTClient()

# ---------------------------
# Indicator calculations
# ---------------------------
def calculate_vwap(trades):
    total_volume = sum(t["size"] for t in trades)
    if total_volume == 0:
        return 0
    return sum(t["price"] * t["size"] for t in trades) / total_volume

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = prices[-i] - prices[-i-1]
        if delta > 0:
            gains.append(delta)
        else:
            losses.append(abs(delta))
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_trade_size(equity, min_pct=0.02, max_pct=0.10):
    # Risk allocation: scale trade size by account equity
    size = equity * 0.05  # default 5%
    return max(min(size, equity * max_pct), equity * min_pct)

# ---------------------------
# Coinbase requests helper
# ---------------------------
def get_recent_trades(symbol, limit=50):
    url = f"{client.base_url}/market/trades?symbol={symbol}&limit={limit}"
    resp = requests.get(url)
    if resp.status_code != 200:
        logger.error(f"Failed fetching trades for {symbol}: {resp.text}")
        return []
    data = resp.json()
    return [{"price": float(t["price"]), "size": float(t["size"])} for t in data]

async def execute_order(symbol, side, size, price=None):
    try:
        data = {
            "product_id": symbol,
            "side": side,
            "size": str(size),
        }
        if price:
            data["price"] = str(price)
            data["type"] = "limit"
        else:
            data["type"] = "market"
        resp = client.request("POST", "/trading/orders", data)
        logger.info(f"{symbol} {side} order executed: {resp}")
        return resp
    except Exception as e:
        logger.error(f"Failed to execute {side} order for {symbol}: {e}")

# ---------------------------
# Main trading logic per pair/account
# ---------------------------
async def trade_symbol(symbol, account):
    try:
        trades = get_recent_trades(symbol)
        prices = [t["price"] for t in trades]

        vwap = calculate_vwap(trades)
        rsi = calculate_rsi(prices)

        equity = float(account["balance"]["amount"])
        trade_size = calculate_trade_size(equity)

        logger.info(f"{symbol} | Account: {account['currency']} | VWAP: {vwap} | RSI: {rsi} | Trade Size: {trade_size}")

        # Signal logic
        if rsi < 30:
            await execute_order(symbol, "buy", trade_size)
        elif rsi > 70:
            await execute_order(symbol, "sell", trade_size)
        else:
            logger.info(f"No trade signal for {symbol} | RSI: {rsi}")

    except Exception as e:
        logger.error(f"Error trading {symbol}: {e}")

# ---------------------------
# Multi-account / multi-pair runner
# ---------------------------
async def trade_loop(symbols):
    while True:
        accounts = client.list_accounts()
        if not accounts:
            logger.warning("No accounts available, retrying in 5s...")
            await asyncio.sleep(5)
            continue

        tasks = []
        for account in accounts:
            for symbol in symbols:
                tasks.append(trade_symbol(symbol, account))
        await asyncio.gather(*tasks)
        await asyncio.sleep(5)  # loop delay

# ---------------------------
# Entry point
# ---------------------------
if __name__ == "__main__":
    symbols_to_trade = ["BTC-USD", "ETH-USD", "SOL-USD"]  # add any pair
    logger.info("Starting Nija Dynamic Aggressive Trading Bot...")
    asyncio.run(trade_loop(symbols_to_trade))
