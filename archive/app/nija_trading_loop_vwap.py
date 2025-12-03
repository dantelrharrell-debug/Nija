import os
import asyncio
import logging
from nija_coinbase_jwt_client import CoinbaseJWTClient
from trading_logic import (
    fetch_prices,
    compute_vwap,
    compute_rsi,
    compute_volatility,
    get_account_balance,
    get_trade_size,
    execute_order,
    check_trailing
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.vwap_rsi")

# --- Config ---
MIN_ALLOCATION = 0.02  # 2%
MAX_ALLOCATION = 0.1   # 10%
FAST_VWAP_WINDOW = 5
SLOW_VWAP_WINDOW = 20

# --- Global state for open trades ---
TRADE_STATE = {}

# --- Coinbase client ---
client = CoinbaseJWTClient()
accounts = client.get_accounts()  # ensure your JWT client is working

# --- VWAP crossover ---
def compute_fast_slow_vwap(prices):
    fast_vwap = compute_vwap(prices[-FAST_VWAP_WINDOW:]) if len(prices) >= FAST_VWAP_WINDOW else compute_vwap(prices)
    slow_vwap = compute_vwap(prices[-SLOW_VWAP_WINDOW:]) if len(prices) >= SLOW_VWAP_WINDOW else compute_vwap(prices)
    return fast_vwap, slow_vwap

# --- Core trading loop per account & symbol ---
async def trade_account_symbol(account, symbol):
    account_id = account["id"]
    balance = get_account_balance([account])
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

    # --- VWAP crossover signals ---
    if fast_vwap > slow_vwap and rsi < 70 and symbol not in TRADE_STATE[account_id]:
        # Buy signal
        resp = await execute_order(account_id, symbol, "buy", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {
                "side": "buy",
                "entry": price,
                "size": trade_size,
                "ttp": price * 1.01,  # 1% trailing take-profit
                "tsl": price * 0.98   # 2% trailing stop-loss
            }
            logger.info(f"[{account_id}] Bought {symbol} @ {price}")

    elif fast_vwap < slow_vwap and rsi > 30 and symbol not in TRADE_STATE[account_id]:
        # Sell signal
        resp = await execute_order(account_id, symbol, "sell", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {
                "side": "sell",
                "entry": price,
                "size": trade_size,
                "ttp": price * 0.99,  # 1% trailing take-profit
                "tsl": price * 1.02   # 2% trailing stop-loss
            }
            logger.info(f"[{account_id}] Sold {symbol} @ {price}")

    # --- Trailing take-profit / stop-loss ---
    await check_trailing(account_id, symbol, prices)

# --- Multi-account, multi-symbol loop ---
async def main_loop(symbols):
    while True:
        tasks = []
        for account in accounts:
            for symbol in symbols:
                tasks.append(trade_account_symbol(account, symbol))
        await asyncio.gather(*tasks)
        await asyncio.sleep(5)  # loop every 5 seconds

if __name__ == "__main__":
    # Symbols you want to trade
    SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]
    asyncio.run(main_loop(SYMBOLS))
