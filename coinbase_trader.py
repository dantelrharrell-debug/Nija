import time
import logging
import pandas as pd
from nija_client import CoinbaseClient
from config import SPOT_TICKERS, LIVE_TRADING

logger = logging.getLogger("CoinbaseTrader")
logging.basicConfig(level=logging.INFO)

def compute_indicators(price_data):
    df = pd.DataFrame(price_data)
    df['rsi'] = 100 - (100 / (1 + df['close'].pct_change().rolling(14).mean()))
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    return df

def coinbase_loop():
    client = CoinbaseClient()
    while True:
        try:
            for ticker in SPOT_TICKERS:
                price_data = client.fetch_ohlcv(ticker, limit=100)
                indicators = compute_indicators(price_data)
                rsi = indicators['rsi'].iloc[-1]
                vwap = indicators['vwap'].iloc[-1]

                if LIVE_TRADING:
                    if rsi < 30 and price_data['close'].iloc[-1] < vwap:
                        logger.info(f"BUY {ticker} at {price_data['close'].iloc[-1]}")
                        client.place_order("buy", ticker)
                    elif rsi > 70 and price_data['close'].iloc[-1] > vwap:
                        logger.info(f"SELL {ticker} at {price_data['close'].iloc[-1]}")
                        client.place_order("sell", ticker)
            time.sleep(60)
        except Exception as e:
            logger.error(f"Coinbase loop error: {e}")
            time.sleep(10)
