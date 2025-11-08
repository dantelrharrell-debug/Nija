import time
import logging
import pandas as pd
from nija_coinbase_jwt_client import CoinbaseJWTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot")

# --- Settings ---
TRADING_PAIRS = ["BTC-USD", "ETH-USD", "ADA-USD"]  # Add your pairs
TRADE_AMOUNT = 0.01  # adjust per pair
TRADE_INTERVAL = 5  # seconds between checks

# --- Initialize JWT client ---
client = CoinbaseJWTClient()

# --- Placeholder: fetch market data (replace with real API or indicators) ---
def fetch_market_data(symbol):
    import numpy as np
    now = pd.Timestamp.now()
    data = {
        "open": [100 + np.random.rand() for _ in range(10)],
        "high": [101 + np.random.rand() for _ in range(10)],
        "low": [99 + np.random.rand() for _ in range(10)],
        "close": [100 + np.random.rand() for _ in range(10)],
        "volume": [10 + np.random.rand() for _ in range(10)],
        "timestamp": [now - pd.Timedelta(seconds=i*60) for i in range(10)]
    }
    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    return df

# --- Example Indicator Logic ---
def simple_signal(df):
    # placeholder: buy if last close > first close
    if df["close"].iloc[-1] > df["close"].iloc[0]:
        return {"buy_signal": True}
    return {"buy_signal": False}

# --- Main Loop ---
def run_trading_bot():
    logger.info("[NIJA] Trading bot started")
    while True:
        try:
            for pair in TRADING_PAIRS:
                df = fetch_market_data(pair)
                signals = simple_signal(df)
                side = "buy" if signals.get("buy_signal") else "sell"
                response = client.place_trade(pair, side, TRADE_AMOUNT)
                logger.info("[NIJA] %s %s trade response: %s", side.upper(), pair, response)
            time.sleep(TRADE_INTERVAL)
        except KeyboardInterrupt:
            logger.info("[NIJA] Bot stopped manually")
            break
        except Exception as e:
            logger.error("[NIJA] Error in bot loop: %s", e)
            time.sleep(TRADE_INTERVAL)

# --- Test accounts before live ---
if __name__ == "__main__":
    accounts = client.list_accounts()
    logger.info("[NIJA] Accounts: %s", accounts)
    run_trading_bot()
