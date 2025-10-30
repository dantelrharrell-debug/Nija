#!/usr/bin/env python3
# nija_render_worker.py
import os
import time
import logging
from decimal import Decimal
import numpy as np
from nija_client import client  # uses the live Coinbase client

# ---------------------
# Logging
# ---------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

# ---------------------
# Trading Parameters
# ---------------------
MIN_ALLOCATION = 0.02  # 2% minimum
MAX_ALLOCATION = 0.10  # 10% maximum
PRICE_HISTORY_LENGTH = 60  # Track last 60 price points
TRADE_PRODUCT = "BTC-USD"

price_history = []

# ---------------------
# Adaptive Trade Sizing
# ---------------------
def calculate_risk_factor(volatility: float) -> float:
    if volatility > 0.05:  # High volatility
        return 0.03
    elif volatility > 0.02:  # Medium
        return 0.05
    else:  # Low
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
    logger.info("[NIJA] Render worker started (background) - LIVE trading")
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

            # Simple adaptive trading strategy
            if len(price_history) >= 20:
                short_ma = np.mean(price_history[-5:])
                long_ma = np.mean(price_history[-20:])
                if short_ma > long_ma:  # Buy signal
                    execute_buy(usd_balance, latest_price)
                elif short_ma < long_ma:  # Sell signal
                    execute_sell(usd_balance, latest_price)

            time.sleep(10)  # Wait 10 seconds between cycles

        except Exception as e:
            logger.error(f"[NIJA] ERROR: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_worker()
