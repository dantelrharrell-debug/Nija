#!/usr/bin/env python3
# nija_live_snapshot.py
import os
import time
import logging
from typing import Tuple

# --- Shadow-folder cleanup (prevents pip import shadowing) ---
import shutil
for name in ("coinbase_advanced_py", "coinbase-advanced-py"):
    folder = os.path.join(os.getcwd(), name)
    if os.path.isdir(folder):
        backup = os.path.join(os.getcwd(), "local_shadow_backups", name)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        try:
            shutil.move(folder, backup)
            # use basic logging until the main logger is configured
            print(f"[NIJA] Moved local shadow folder {folder} -> {backup}")
        except Exception as e:
            print(f"[NIJA] Failed to move shadow folder {folder}: {e}")

# --- Logging setup ---
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("nija.live")

# --- Import shared modules (these should exist in repo) ---
# nija_client.py must expose `client`
from nija_client import client
from trading_logic import place_order
from indicators import calculate_indicators

# --- Helper: fetch market data (attempt real candles via client, fallback to simulated) ---
def fetch_market_data(symbol: str = "BTC-USD", limit: int = 100) -> Tuple[object, object]:
    """
    Returns (df, signals) where df is a pandas.DataFrame and signals is dict from calculate_indicators.
    This function will attempt to use the client's candle/candles endpoint if available; otherwise it simulates.
    """
    import pandas as pd
    try:
        # prefer client method names that might exist
        if client and hasattr(client, "get_candles"):
            candles = client.get_candles(symbol=symbol, limit=limit)  # shape depends on client
            # Expecting list-of-lists or list-of-dicts - try to normalize
            # many Coinbase endpoints return list of [time, low, high, open, close, volume]
            if isinstance(candles, list) and len(candles) and isinstance(candles[0], (list, tuple)):
                df = pd.DataFrame(candles, columns=["time", "low", "high", "open", "close", "volume"])
            else:
                # try list-of-dicts or DataFrame-friendly structure
                df = pd.DataFrame(candles)
            df = df.sort_values("time")
        else:
            # Simulated data (client is DummyClient)
            import numpy as np
            now = pd.Timestamp.now()
            data = {
                "open": [100 + np.random.rand() for _ in range(50)],
                "high": [101 + np.random.rand() for _ in range(50)],
                "low": [99 + np.random.rand() for _ in range(50)],
                "close": [100 + np.random.rand() for _ in range(50)],
                "volume": [10 + np.random.rand() for _ in range(50)],
                "time": [now - pd.Timedelta(seconds=i * 60) for i in range(50)]
            }
            df = pd.DataFrame(data)
            df.set_index("time", inplace=False)
    except Exception as e:
        logger.error("[NIJA] fetch_market_data: client fetch failed: %s -- falling back to simulated data", e)
        import numpy as np
        now = pd.Timestamp.now()
        data = {
            "open": [100 + np.random.rand() for _ in range(50)],
            "high": [101 + np.random.rand() for _ in range(50)],
            "low": [99 + np.random.rand() for _ in range(50)],
            "close": [100 + np.random.rand() for _ in range(50)],
            "volume": [10 + np.random.rand() for _ in range(50)],
            "time": [now - pd.Timedelta(seconds=i * 60) for i in range(50)]
        }
        df = pd.DataFrame(data)

    # --- PREPROCESS: convert numeric columns and forward-fill (no deprecated fillna(method=...)) ---
    try:
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric, errors='coerce').ffill()
    except Exception as e:
        logger.warning("[NIJA] Data preprocessing failed: %s", e)

    # --- Calculate indicators ---
    try:
        signals = calculate_indicators(df)
    except Exception as e:
        logger.error("[NIJA] Indicator calc failed: %s", e)
        signals = {}

    return df, signals

# --- Startup live check ---
def startup_live_check():
    logger.info("[NIJA] Performing startup live check...")
    try:
        # Attempt to read an account or do a harmless REST ping
        if client and hasattr(client, "get_account"):
            acct = client.get_account()
            logger.info("[NIJA] Live client present. sample account: %s", acct)
            return True
        else:
            logger.warning("[NIJA] No live client methods available; running in SIMULATION.")
            return False
    except Exception as e:
        logger.warning("[NIJA] Exception while checking live client: %s -- running in SIMULATION", e)
        return False

# --- Main trading loop ---
def run_trading_bot():
    # Symbols to check - adjust to your trading pairs
    TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC-USD,ETH-USD,XRP-USD,ADA-USD").split(",")
    TRADE_TYPE = os.getenv("TRADE_TYPE", "Spot")  # "Spot" or "Futures"
    TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", "1"))  # default amount per trade
    INTERVAL = int(os.getenv("TRADE_INTERVAL", "5"))  # seconds between cycles

    is_live = startup_live_check()
    logger.info("[NIJA] Trading loop starting. Live mode: %s", is_live)

    while True:
        try:
            for symbol in TRADING_PAIRS:
                symbol = symbol.strip()
                df, signals = fetch_market_data(symbol)

                if df is None or signals is None:
                    logger.warning("[NIJA] No data/signals for %s — skipping", symbol)
                    continue

                # Example: simple decision logic (you can replace with your strategy)
                side = None
                if signals.get("buy_signal"):
                    side = "buy"
                elif signals.get("sell_signal"):
                    side = "sell"

                if side:
                    resp = place_order(symbol, TRADE_TYPE, side, TRADE_AMOUNT)
                    logger.info("[NIJA] place_order response for %s: %s", symbol, resp)
                else:
                    logger.debug("[NIJA] No trade signal for %s", symbol)

            time.sleep(INTERVAL)

        except KeyboardInterrupt:
            logger.info("[NIJA] Bot stopped by KeyboardInterrupt")
            return
        except Exception as e:
            logger.exception("[NIJA] Unexpected error in trading loop: %s", e)
            time.sleep(5)

# --- If invoked directly, run a single startup check then start the loop ---
if __name__ == "__main__":
    logger.info("=== NIJA Live Snapshot ENTRYPOINT ===")
    run_trading_bot()
