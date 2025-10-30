#!/usr/bin/env python3
# nija_live_worker.py
import os
import time
import logging
from decimal import Decimal
import numpy as np

# ---------------------
# Logging
# ---------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_live")

# ---------------------
# Coinbase Client Setup
# ---------------------
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not found, using dummy client")

    class DummyClient:
        def buy(self, product_id, amount):
            logger.info(f"[DummyClient] Simulated BUY {amount} {product_id}")

        def sell(self, product_id, amount):
            logger.info(f"[DummyClient] Simulated SELL {amount} {product_id}")

        def get_product_ticker(self, product_id):
            return {"price": 29500.0}  # Dummy price

        def get_accounts(self):
            return {"USD": 1000.0}  # Dummy USD balance

    CoinbaseClient = DummyClient

# ---------------------
# API Keys
# ---------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)

# ---------------------
# Trading Parameters
# ---------------------
MIN_ALLOCATION = 0.02  # 2% min
MAX_ALLOCATION = 0.10  # 10% max
PRICE_HISTORY_LENGTH = 60
TRADE_PRODUCT = "BTC-USD"

price_history = []

# ---------------------
# Adaptive Trade Sizing
# ---------------------
def calculate_risk_factor(volatility: float) -> float:
    if volatility > 0.05:
        return 0.03
    elif volatility > 0.02:
        return 0.05
    else:
        return 0.08

def get_trade_amount(account_balance: float, volatility: float) -> float:
    risk_factor = calculate_risk_factor(volatility)
    trade_amount = account_balance * risk_factor
    trade_amount = max(trade_amount, account_balance * MIN_ALLOCATION)
    trade_amount = min(trade_amount, account_balance * MAX_ALLOCATION)
    return round(trade_amount, 2)

def calculate_volatility(price_history: list) -> float:
    if len(price_history) < 2:
        return 0.0
    returns = np.diff(price_history) / price_history[:-1]
    return float(np.std(returns))

# ---------------------
# Trade Execution
# ---------------------
def execute_buy(account_balance: float, current_price: float):
    volatility = calculate_volatility(price_history)
    trade_usd = get_trade_amount(account_balance, volatility)
    btc_amount = trade_usd / current_price
    logger.info(f"[NIJA] BUY: ${trade_usd} (~{btc_amount:.6f} BTC) @ ${current_price}")
    client.buy(product_id=TRADE_PRODUCT, amount=btc_amount)

def execute_sell(account_balance: float, current_price: float):
    volatility = calculate_volatility(price_history)
    trade_usd = get_trade_amount(account_balance, volatility)
    btc_amount = trade_usd / current_price
    logger.info(f"[NIJA] SELL: ${trade_usd} (~{btc_amount:.6f} BTC) @ ${current_price}")
    client.sell(product_id=TRADE_PRODUCT, amount=btc_amount)

# ---------------------
# Main Worker Loop
# ---------------------
def run_worker():
    global price_history
    logger.info("[NIJA] Worker started - LIVE trading")
    while True:
        try:
            # Fetch current price
            ticker = client.get_product_ticker(TRADE_PRODUCT)
            latest_price = float(ticker['price'])
            price_history.append(latest_price)

            # Keep price history capped
            if len(price_history) > PRICE_HISTORY_LENGTH:
                price_history.pop(0)

            # Fetch account balance
            account_info = client.get_accounts()
            usd_balance = float(account_info.get('USD', 0.0))

            # Simple moving average strategy
            if len(price_history) >= 20:
                short_ma = np.mean(price_history[-5:])
                long_ma = np.mean(price_history[-20:])
                if short_ma > long_ma:
                    execute_buy(usd_balance, latest_price)
                elif short_ma < long_ma:
                    execute_sell(usd_balance, latest_price)

            time.sleep(10)  # 10 seconds cycle

        except Exception as e:
            logger.error(f"[NIJA] ERROR: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_worker()
