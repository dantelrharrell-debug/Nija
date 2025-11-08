import os
import time
import logging
import pandas as pd
from nija_coinbase_jwt_client import CoinbaseJWTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.jwt")

# --- Initialize JWT Client ---
client = CoinbaseJWTClient()

# --- Bot Settings ---
TRADING_PAIRS = ["BTC-USD", "ETH-USD", "XRP-USD", "ADA-USD", "LTC-USD", "SOL-USD", "BNB-USD"]
TRADE_AMOUNT = 0.001  # small test amount
TRADE_INTERVAL = 5    # seconds between market checks

# --- Fetch Market Data ---
def fetch_market_data(symbol, granularity=60, limit=100):
    """
    Fetch OHLC data from Coinbase Advanced API using JWT client.
    """
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

# --- Indicator Calculation ---
def calculate_indicators(df):
    """
    Simple SMA crossover strategy:
    Buy if fast MA > slow MA, else sell.
    """
    if df.empty or len(df) < 20:
        return {"buy_signal": False}

    df['fast_ma'] = df['close'].rolling(5).mean()
    df['slow_ma'] = df['close'].rolling(20).mean()

    return {"buy_signal": df['fast_ma'].iloc[-1] > df['slow_ma'].iloc[-1]}

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
    logger.info("[NIJA] JWT Trading bot started")
    while True:
        try:
            for symbol in TRADING_PAIRS:
                df = fetch_market_data(symbol)
                if df.empty:
                    continue

                signals = calculate_indicators(df)
                side = "buy" if signals.get("buy_signal") else "sell"

                place_order(symbol, side, TRADE_AMOUNT)

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
