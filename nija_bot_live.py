# nija_bot_live.py
from nija_client import CoinbaseClient
import time
import logging
import pandas as pd

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot")

# --- Initialize Coinbase Client ---
client = CoinbaseClient(
    pem_file="/path/to/NijaBotWalletKeyAdvanced.pem",  # <- Replace with your PEM path
    key_id="YOUR_KEY_ID_HERE",                        # <- Replace with your Key ID
    passphrase="YOUR_PASSPHRASE_HERE"                # <- Replace with your Passphrase
)

# --- Bot Settings ---
TRADING_PAIRS = ["BTC-USD", "ETH-USD", "XRP-USD", "ADA-USD", "LTC-USD", "SOL-USD", "BNB-USD"]
TRADE_TYPE = "Spot"
TRADE_AMOUNT = 0.001  # small test amount
TRADE_INTERVAL = 5    # seconds between market checks

# --- Fetch Real Market Data ---
def fetch_market_data(symbol, granularity=60, limit=100):
    """
    Fetch OHLC market data from Coinbase Advanced API.
    """
    try:
        candles = client.get_candles(product_id=symbol, granularity=granularity, limit=limit)
        df = pd.DataFrame(candles)
        df.rename(columns={
            'time': 'timestamp',
            'low': 'low',
            'high': 'high',
            'open': 'open',
            'close': 'close',
            'volume': 'volume'
        }, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df = df.apply(pd.to_numeric, errors='coerce').ffill()
        return df
    except Exception as e:
        logger.error(f"[NIJA] Error fetching market data for {symbol}: {e}")
        return pd.DataFrame()

# --- Calculate Indicators ---
def calculate_indicators(df):
    """
    Simple Moving Average crossover strategy:
    - Buy if fast MA > slow MA
    - Sell if fast MA < slow MA
    """
    if df.empty or len(df) < 20:
        return {"buy_signal": False}

    df['fast_ma'] = df['close'].rolling(5).mean()
    df['slow_ma'] = df['close'].rolling(20).mean()

    if df['fast_ma'].iloc[-1] > df['slow_ma'].iloc[-1]:
        return {"buy_signal": True}
    else:
        return {"buy_signal": False}

# --- Place Order ---
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
                # Fetch real market data
                df = fetch_market_data(symbol, granularity=60)
                if df.empty:
                    continue

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

# --- Run Bot ---
if __name__ == "__main__":
    run_trading_bot()
