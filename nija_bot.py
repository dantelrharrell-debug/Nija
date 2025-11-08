# nija_bot.py
from nija_client import CoinbaseClient
import time
import logging
import pandas as pd
import numpy as np

# --- Optional: your custom trading modules ---
# from trading_logic import place_order
# from indicators import calculate_indicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot")

# --- Initialize Coinbase Client ---
client = CoinbaseClient(
    pem_file="/path/to/NijaBotWalletKeyAdvanced.pem",  # <- Replace with your PEM path
    key_id="YOUR_KEY_ID_HERE",                        # <- Replace with your Key ID
    passphrase="YOUR_PASSPHRASE_HERE"                # <- Replace with your Passphrase
)

# --- Bot settings ---
TRADING_PAIRS = ["BTC-USD", "ETH-USD", "XRP-USD", "ADA-USD", "LTC-USD", "SOL-USD", "BNB-USD"]
TRADE_TYPE = "Spot"
TRADE_AMOUNT = 0.001  # Small test amount per trade
TRADE_INTERVAL = 5    # Seconds between market checks

# --- Example placeholder functions ---

def fetch_market_data(symbol):
    """
    Fetch market data for a symbol.
    This is a dummy function for testing signals.
    Replace with real Coinbase API data if desired.
    """
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

def calculate_indicators(df):
    """
    Dummy indicator calculation.
    Replace with your real strategy.
    """
    # Example: simple random buy/sell signal
    return {"buy_signal": np.random.choice([True, False])}

def place_order(symbol, trade_type, side, amount):
    """
    Places a market order using the Coinbase client.
    """
    try:
        order = client.create_trade(
            product_id=symbol,
            side=side,
            size=str(amount),
            type="market"
        )
        return order
    except Exception as e:
        logger.error(f"[NIJA] Error placing order for {symbol}: {e}")
        return None

# --- Main Trading Loop ---
def run_trading_bot():
    logger.info("[NIJA] Trading bot started. Live mode: %s", bool(client))
    while True:
        try:
            for symbol in TRADING_PAIRS:
                # Fetch market data
                df = fetch_market_data(symbol)
                df = df.apply(pd.to_numeric, errors='coerce').ffill()

                # Calculate indicators
                signals = calculate_indicators(df)
                side = "buy" if signals.get("buy_signal") else "sell"

                # Place order
                response = place_order(symbol, TRADE_TYPE, side, TRADE_AMOUNT)
                logger.info("[NIJA] %s order response: %s", symbol, response)

            time.sleep(TRADE_INTERVAL)

        except KeyboardInterrupt:
            logger.info("[NIJA] Bot stopped manually")
            break
        except Exception as e:
            logger.error(f"[NIJA] Unexpected error in main loop: {e}")
            time.sleep(TRADE_INTERVAL)

# --- Run bot ---
if __name__ == "__main__":
    run_trading_bot()
