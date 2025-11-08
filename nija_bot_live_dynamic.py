import os
import asyncio
import logging
import time
import pandas as pd
from nija_coinbase_jwt_client import CoinbaseJWTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.pro")

# --- Initialize Coinbase JWT Client ---
client = CoinbaseJWTClient()

# --- Example symbols ---
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]

# --- Trade state per account per symbol ---
TRADE_STATE = {}  # TRADE_STATE[account_id][symbol] = {trade info}
LAST_TRADE = {}   # Last trade timestamp per symbol for rate limiting

# --- Trading parameters ---
MIN_ALLOCATION = 0.02  # 2% per trade
MAX_ALLOCATION = 0.10  # 10% per trade
VOLATILITY_FACTOR = 0.5  # dynamic allocation adjustment
VWAP_WINDOW = 14
RSI_PERIOD = 14
FAST_VWAP_WINDOW = 5
SLOW_VWAP_WINDOW = 20

# --- Helper functions ---
def compute_vwap(prices):
    return sum(prices) / len(prices)

def compute_rsi(prices, period=RSI_PERIOD):
    deltas = pd.Series(prices).diff().dropna()
    gain = deltas.clip(lower=0).rolling(period).mean()
    loss = -deltas.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else 50

def compute_volatility(prices):
    return pd.Series(prices).pct_change().std()

def compute_fast_slow_vwap(prices):
    fast_vwap = compute_vwap(prices[-FAST_VWAP_WINDOW:]) if len(prices) >= FAST_VWAP_WINDOW else compute_vwap(prices)
    slow_vwap = compute_vwap(prices[-SLOW_VWAP_WINDOW:]) if len(prices) >= SLOW_VWAP_WINDOW else compute_vwap(prices)
    return fast_vwap, slow_vwap

def get_trade_size(account_balance, allocation, volatility):
    size = account_balance * allocation * (1 - volatility * VOLATILITY_FACTOR)
    return max(size, 0)

async def dynamic_sleep(symbol):
    now = time.time()
    last = LAST_TRADE.get(symbol, 0)
    sleep_time = max(1, 10 - (now - last))  # e.g., min 1s, max 10s
    await asyncio.sleep(sleep_time)
    LAST_TRADE[symbol] = time.time()

# --- Coinbase wrappers ---
def get_accounts():
    return client.get_accounts()

def get_account_balance(account):
    total = 0
    for a in account:
        if a["currency"] == "USD":
            total += float(a["balance"]["available"])
    return total

async def fetch_prices(symbol):
    resp = client.request("GET", f"/market_data/{symbol}/candles?granularity=60")
    df = pd.DataFrame(resp)
    df["close"] = df["close"].astype(float)
    return df["close"].tolist()

async def execute_order(account_id, symbol, side, size):
    logger.info(f"[{account_id}] Executing {side.upper()} order for {symbol}, size {size:.4f}")
    data = {"side": side, "size": size, "symbol": symbol}
    resp = client.request("POST", "/orders", data)
    return resp

# --- Trailing Take-Profit & Stop-Loss ---
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

# --- Trading logic per account per symbol ---
async def trade_account_symbol(account, symbol):
    await dynamic_sleep(symbol)  # rate limiting per symbol
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
        resp = await execute_order(account_id, symbol, "buy", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {
                "side": "buy",
                "entry": price,
                "size": trade_size,
                "ttp": price * 1.01,
                "tsl": price * 0.98
            }

    elif fast_vwap < slow_vwap and rsi > 30 and symbol not in TRADE_STATE[account_id]:
        resp = await execute_order(account_id, symbol, "sell", trade_size)
        if resp:
            price = prices[-1]
            TRADE_STATE[account_id][symbol] = {
                "side": "sell",
                "entry": price,
                "size": trade_size,
                "ttp": price * 0.99,
                "tsl": price * 1.02
            }

    await check_trailing(account_id, symbol, prices)

# --- Main loop ---
async def main_loop():
    while True:
        accounts = get_accounts()
        tasks = []
        for account in accounts:
            for symbol in SYMBOLS:
                tasks.append(trade_account_symbol(account, symbol))
        await asyncio.gather(*tasks)
        await asyncio.sleep(60)  # recalc every minute

# --- Run bot ---
if __name__ == "__main__":
    asyncio.run(main_loop())
