import os
import time
import logging
import pandas as pd
import numpy as np
from nija_coinbase_jwt_client import CoinbaseJWTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.jwt.v2")

# --- Initialize JWT Client ---
client = CoinbaseJWTClient()

# --- Bot Settings ---
TRADING_PAIRS = ["BTC-USD", "ETH-USD", "XRP-USD", "ADA-USD", "LTC-USD", "SOL-USD", "BNB-USD"]
MIN_TRADE_PERCENT = 0.02  # 2% of account equity
MAX_TRADE_PERCENT = 0.10  # 10% of account equity
TRADE_INTERVAL = 5  # seconds between market checks
VWAP_PERIOD = 14
RSI_PERIOD = 14

# --- Fetch Market Data ---
def fetch_market_data(symbol, granularity=60, limit=100):
    path = f"/platform/v1/candles?product_id={symbol}&granularity={granularity}&limit={limit}"
    try:
        data = client.request("GET", path)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df.rename(columns={
            "time": "timestamp",
            "low": "low",
            "high": "high",
            "open": "open",
            "close": "close",
            "volume": "volume"
        }, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df = df.apply(pd.to_numeric, errors='coerce').ffill()
        return df
    except Exception as e:
        logger.error("[NIJA] Error fetching market data for %s: %s", symbol, e)
        return pd.DataFrame()

# --- Calculate Indicators: SMA, VWAP, RSI ---
def calculate_indicators(df):
    if df.empty or len(df) < max(VWAP_PERIOD, RSI_PERIOD):
        return {"buy_signal": False, "sell_signal": False}

    # SMA crossover
    df['fast_ma'] = df['close'].rolling(5).mean()
    df['slow_ma'] = df['close'].rolling(20).mean()
    
    # VWAP
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    
    # RSI
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    roll_up = up.rolling(RSI_PERIOD).mean()
    roll_down = down.rolling(RSI_PERIOD).mean()
    rs = roll_up / roll_down
    df['rsi'] = 100 - (100 / (1 + rs))

    # Signals
    buy_signal = (df['fast_ma'].iloc[-1] > df['slow_ma'].iloc[-1]) and (df['close'].iloc[-1] > df['vwap'].iloc[-1]) and (df['rsi'].iloc[-1] < 70)
    sell_signal = (df['fast_ma'].iloc[-1] < df['slow_ma'].iloc[-1]) and (df['close'].iloc[-1] < df['vwap'].iloc[-1]) and (df['rsi'].iloc[-1] > 30)

    return {"buy_signal": buy_signal, "sell_signal": sell_signal}

# --- Dynamic trade sizing ---
def get_trade_amount(account_balance, symbol):
    amount = account_balance * MIN_TRADE_PERCENT
    if amount > account_balance * MAX_TRADE_PERCENT:
        amount = account_balance * MAX_TRADE_PERCENT
    return round(amount, 8)  # round for precision

# --- Place Order ---
def place_order(symbol, side, amount):
    path = "/platform/v1/trades"
    order_data = {
        "product_id": symbol,
        "side": side,
        "size": str(amount),
        "type": "market"
    }
    try:
        resp = client.request("POST", path, data=order_data)
        logger.info("[NIJA] Order placed: %s %s", symbol, resp)
        return resp
    except Exception as e:
        logger.error("[NIJA] Error placing order for %s: %s", symbol, e)
        return None

# --- Main Bot Loop ---
def run_trading_bot():
    logger.info("[NIJA] JWT Trading bot v2 started")
    while True:
        try:
            # Fetch account info for dynamic sizing
            accounts = client.get_accounts()
            if not accounts:
                logger.warning("[NIJA] No accounts returned. Skipping this loop.")
                time.sleep(TRADE_INTERVAL)
                continue

            # For simplicity, use first account's balance in USD
            account_balance = float(accounts[0].get("balance", 100))  # default 100 if missing

            for symbol in TRADING_PAIRS:
                df = fetch_market_data(symbol)
                if df.empty:
                    continue

                signals = calculate_indicators(df)
                if signals["buy_signal"]:
                    side = "buy"
                elif signals["sell_signal"]:
                    side = "sell"
                else:
                    continue  # no trade

                trade_amount = get_trade_amount(account_balance, symbol)
                if trade_amount <= 0:
                    continue

                place_order(symbol, side, trade_amount)

            time.sleep(TRADE_INTERVAL)

        except KeyboardInterrupt:
            logger.info("[NIJA] Bot stopped manually")
            break
        except Exception as e:
            logger.error("[NIJA] Unexpected error in main loop: %s", e)
            time.sleep(TRADE_INTERVAL)

# --- Run Bot ---
if __name__ == "__main__":
    run_trading_bot()
