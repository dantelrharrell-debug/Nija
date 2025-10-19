

import os
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional

# External Coinbase client
# Make sure coinbase_advanced_py is installed and supports these methods for your account
from coinbase_advanced_py import CoinbaseClient

# Load API keys from environment (recommended)
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    print("WARNING: COINBASE_API_KEY or COINBASE_API_SECRET not set. Set them before running in production.")

client = CoinbaseClient(API_KEY, API_SECRET)

# Pairs to trade
TRADING_PAIRS = ["BTC-USD", "ETH-USD"]

# Default risk percent (can be 2 - 10)
DEFAULT_RISK_PERCENT = 5

# In-memory live data store (updated by websocket)
live_data = {pair: pd.DataFrame(columns=["time", "price", "volume"]) for pair in TRADING_PAIRS}


def get_account_balance(currency: str = "USD") -> float:
    """
    Return available balance for the given currency (USD).
    If API client differs, adapt this method to your client's response format.
    """
    try:
        accounts = client.get_accounts()
        for acct in accounts:
            if acct.get("currency") == currency:
                return float(acct.get("available", 0))
    except Exception as e:
        print("❌ Error fetching balance:", e)
    return 0.0


def calculate_position_size(balance: float, risk_percent: float = DEFAULT_RISK_PERCENT) -> float:
    """
    Calculate amount in USD to risk (rounded).
    For coinbase order API you may need to convert USD amount to base currency units.
    """
    if balance <= 0:
        return 0.0
    risk_percent = max(2.0, min(10.0, float(risk_percent)))  # clamp 2-10%
    size = balance * (risk_percent / 100.0)
    # round to reasonable precision (string later for API)
    return round(size, 8)


def update_live_data(pair: str, price: float, volume: float, timestamp: datetime):
    """
    Append new ticker datapoint and keep the last 200 points.
    """
    global live_data
    df = live_data.get(pair)
    if df is None:
        df = pd.DataFrame(columns=["time", "price", "volume"])
    row = {"time": timestamp, "price": float(price), "volume": float(volume)}
    df = df.append(row, ignore_index=True)
    live_data[pair] = df.tail(200)


def calculate_vwap(df: pd.DataFrame) -> float:
    if df is None or df.empty or df["volume"].sum() == 0:
        return 0.0
    return float((df["price"] * df["volume"]).sum() / df["volume"].sum())


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    if df is None or len(df) < period:
        return 50.0
    delta = df["price"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    last = rsi.iloc[-1]
    if pd.isna(last):
        return 50.0
    return float(last)


def ai_signal(pair: str) -> str:
    """
    Basic VWAP + RSI rule:
     - buy: price > vwap and rsi < 70
     - sell: price < vwap and rsi > 30
     - hold otherwise
    Replace this with upgraded ML or weighted logic when ready.
    """
    df = live_data.get(pair)
    if df is None or df.empty:
        return "hold"
    vwap = calculate_vwap(df)
    rsi = calculate_rsi(df)
    latest_price = float(df["price"].iloc[-1])
    if latest_price > vwap and rsi < 70:
        return "buy"
    if latest_price < vwap and rsi > 30:
        return "sell"
    return "hold"


def place_order(symbol: str, side: str, usd_amount: float) -> Optional[dict]:
    """
    Place a market order using Coinbase Advanced API.
    Note: coinbase_advanced_py may expect size in base currency units (BTC, ETH),
    or may accept 'funds' param specifying USD amount. Inspect your SDK docs.
    This function attempts to place a market order with 'size' as a string.
    If your SDK expects 'funds' (USD), change parameter name accordingly.
    """
    try:
        # If coinbase_advanced_py uses 'funds' for fiat amount, replace 'size' with funds=...
        order = client.place_order(
            product_id=symbol,
            side=side,
            order_type="market",
            size=str(usd_amount)  # adjust if API requires base units
        )
        print(f"✅ {datetime.now()} | Order executed: {side} {usd_amount} USD on {symbol}")
        return order
    except Exception as e:
        print(f"❌ Error placing order for {symbol}: {e}")
        return None
