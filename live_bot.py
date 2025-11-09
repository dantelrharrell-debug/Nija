import os
import time
from decimal import Decimal
from loguru import logger
from nija_client import NijaCoinbaseClient
from nija_balance_helper import get_usd_balance

# --- Logger setup ---
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

logger.info("🚀 Starting Nija Coinbase Live Bot (PEM/JWT mode)")

# --- Initialize client ---
try:
    client = NijaCoinbaseClient()
    logger.info("✅ CoinbaseClient initialized using PEM/JWT (Advanced=True)")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase client: {e}")
    exit(1)

# --- Helper: simulate signal fetching ---
def get_trade_signal():
    """
    Replace with real TradingView/fear-and-greed logic.
    Returns: "BUY", "SELL", or None
    """
    # TODO: connect TradingView TA / custom indicator
    return None

# --- Main trading loop ---
SLEEP_SECONDS = 15  # poll interval
MIN_TRADE_USD = Decimal("10")  # minimum per trade
MAX_TRADE_USD = Decimal("1000")  # max per trade (adjust per account)

while True:
    try:
        usd_balance = get_usd_balance(client)
        logger.info(f"💰 USD Balance: {usd_balance}")

        if usd_balance < MIN_TRADE_USD:
            logger.warning(f"⚠️ Balance too low for trading (<{MIN_TRADE_USD}), skipping trade")
            time.sleep(SLEEP_SECONDS)
            continue

        signal = get_trade_signal()
        if signal is None:
            logger.info("ℹ️ No trade signal detected. Waiting...")
        else:
            trade_amount = min(MAX_TRADE_USD, usd_balance)
            logger.info(f"📊 Signal detected: {signal}. Preparing trade: ${trade_amount}")

            # Execute trade
            if signal == "BUY":
                try:
                    result = client.place_market_order("BTC-USD", "buy", trade_amount)
                    logger.info(f"✅ BUY executed: {result}")
                except Exception as e:
                    logger.error(f"❌ BUY failed: {e}")
            elif signal == "SELL":
                try:
                    result = client.place_market_order("BTC-USD", "sell", trade_amount)
                    logger.info(f"✅ SELL executed: {result}")
                except Exception as e:
                    logger.error(f"❌ SELL failed: {e}")
            else:
                logger.warning(f"⚠️ Unknown signal: {signal}")

        time.sleep(SLEEP_SECONDS)

    except Exception as e:
        logger.exception(f"❌ Exception in trading loop: {e}")
        time.sleep(SLEEP_SECONDS)
