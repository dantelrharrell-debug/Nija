import time
import logging
from loguru import logger
from nija_client import cdp_get
import requests

# -----------------------------
# 1️⃣ Configure bot settings
# -----------------------------
SYMBOL = "BTC-USD"       # Default trading pair
MIN_ALLOCATION = 0.02    # 2% of account
MAX_ALLOCATION = 0.10    # 10% of account
TAKE_PROFIT_PERCENT = 0.03  # 3% profit
TRAILING_PROFIT_PERCENT = 0.01  # 1% trailing

logger.info("🚀 Nija Trading Bot starting...")


# -----------------------------
# 2️⃣ Utility: Fetch account balance
# -----------------------------
def get_usd_balance():
    accounts = cdp_get("/platform/v2/accounts")
    for acc in accounts.get("data", []):
        if acc.get("currency") == "USD":
            balance = float(acc.get("available_balance", {}).get("value", 0))
            logger.info(f"💰 USD Balance: {balance}")
            return balance
    logger.warning("⚠️ USD account not found. Returning 0 balance.")
    return 0.0


# -----------------------------
# 3️⃣ Utility: Calculate trade size
# -----------------------------
def calc_trade_size(balance):
    size = balance * MAX_ALLOCATION
    if size < balance * MIN_ALLOCATION:
        size = balance * MIN_ALLOCATION
    logger.info(f"📏 Trade size calculated: {size}")
    return round(size, 2)


# -----------------------------
# 4️⃣ Placeholder: Get latest price
# -----------------------------
def get_price(symbol=SYMBOL):
    url = f"https://api.coinbase.com/v2/prices/{symbol}/spot"
    try:
        resp = requests.get(url).json()
        price = float(resp["data"]["amount"])
        logger.info(f"💹 Current {symbol} price: {price}")
        return price
    except Exception as e:
        logger.error(f"❌ Failed to fetch price: {e}")
        return None


# -----------------------------
# 5️⃣ Main trade loop (simulation)
# -----------------------------
def trade_loop():
    while True:
        balance = get_usd_balance()
        trade_size = calc_trade_size(balance)
        price = get_price()
        if price:
            # Example logic: Buy if BTC < 30k, Sell if BTC > 35k
            if price < 30000:
                logger.success(f"🚀 Simulated BUY order for ${trade_size} BTC at ${price}")
            elif price > 35000:
                logger.success(f"💸 Simulated SELL order for ${trade_size} BTC at ${price}")
            else:
                logger.info("⏸️ No trade signal, waiting...")
        time.sleep(15)  # Adjust frequency as needed


# -----------------------------
# 6️⃣ Start bot
# -----------------------------
if __name__ == "__main__":
    try:
        trade_loop()
    except KeyboardInterrupt:
        logger.info("🛑 Nija Bot stopped manually.")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
