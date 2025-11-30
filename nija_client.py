# nija_client.py
import os
import logging
import time
from datetime import datetime
from random import uniform  # Example signal generator

# ------------------------------
# Logging Setup
# ------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ------------------------------
# Coinbase Connection
# ------------------------------
try:
    from coinbase_advanced.client import Client
    client = Client(
        api_key="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/ce5dbcbe-ba9f-45a4-a374-5d2618af0ccd",
        api_secret="""-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIC4EDrIQiByWHS5qIrHsMI6SZb0sYSqx744G2kvqr+PCoAoGCCqGSM49
AwEHoUQDQgAE3gkuCL8xUOM81/alCSOLqEtyUmY7A09z7QEAoN/cfCtbAslo6pXR
qONKAu6GS9PS/W3BTFyB6ZJBRzxMZeNzBg==
-----END EC PRIVATE KEY-----"""
    )
    account = client.get_account()  # Basic API test
    logging.info(f"Coinbase connection successful. Account ID: {account['id']}")
except ModuleNotFoundError:
    client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")
except Exception as e:
    client = None
    logging.error(f"Coinbase connection failed: {e}")

# ------------------------------
# Signals Database
# ------------------------------
signals_db = []

def fetch_signals():
    return signals_db

def add_signal(symbol, side, entry_price, stop_loss, take_profit, asset_type):
    signal = {
        'symbol': symbol,
        'side': side,
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'trailing_stop': stop_loss,
        'trailing_take': take_profit,
        'asset_type': asset_type,
        'status': 'pending'
    }
    signals_db.append(signal)
    logging.info(f"Added new signal: {symbol} {side} ({asset_type})")

# ------------------------------
# Position Sizing
# ------------------------------
def calculate_position_size(signal):
    base_risk_percent = 0.05
    if client:
        account_balance = float(client.get_account()['balance']['amount'])
    else:
        account_balance = 1000  # fallback for offline mode
    size = account_balance * base_risk_percent
    logging.info(f"Calculated position size for {signal['symbol']}: {size}")
    return size

# ------------------------------
# Trading Functions
# ------------------------------
def execute_trade(signal, size):
    logging.info(f"Executing trade: {signal['side']} {size} of {signal['symbol']} ({signal['asset_type']})")
    if client:
        try:
            client.place_order(
                symbol=signal['symbol'],
                side=signal['side'],
                size=size
            )
            signal['status'] = 'open'
            signal['entry_time'] = datetime.utcnow()
        except Exception as e:
            logging.error(f"Failed to execute trade for {signal['symbol']}: {e}")
    else:
        signal['status'] = 'open'
        signal['entry_time'] = datetime.utcnow()

def update_trailing_stop(signal):
    if signal.get('status') != 'open':
        return
    current_price = float(client.get_price(signal['symbol'])['amount']) if client else signal['entry_price']
    if signal['side'] == 'buy':
        signal['trailing_stop'] = max(signal.get('trailing_stop', signal['stop_loss']), current_price * 0.98)
    else:
        signal['trailing_stop'] = min(signal.get('trailing_stop', signal['stop_loss']), current_price * 1.02)
    logging.info(f"Updated trailing stop for {signal['symbol']}: {signal['trailing_stop']}")

def update_trailing_take_profit(signal):
    if signal.get('status') != 'open':
        return
    current_price = float(client.get_price(signal['symbol'])['amount']) if client else signal['entry_price']
    if signal['side'] == 'buy':
        signal['trailing_take'] = max(signal.get('trailing_take', signal['take_profit']), current_price * 1.02)
    else:
        signal['trailing_take'] = min(signal.get('trailing_take', signal['take_profit']), current_price * 0.98)
    logging.info(f"Updated trailing take-profit for {signal['symbol']}: {signal['trailing_take']}")

# ------------------------------
# Ultimate NIJA Strategy Logic
# ------------------------------
def generate_nija_signals():
    # Example: Replace with your ultimate Ninja algorithms
    symbols = [
        {'symbol': 'BTC-USD', 'asset_type': 'crypto'},
        {'symbol': 'ETH-USD', 'asset_type': 'crypto'},
        {'symbol': 'AAPL', 'asset_type': 'stock'},
        {'symbol': 'TSLA', 'asset_type': 'stock'}
    ]
    
    for s in symbols:
        # Replace this with your real trading logic
        side = 'buy' if uniform(0, 1) > 0.5 else 'sell'
        entry = uniform(100, 50000)
        sl = entry * 0.98
        tp = entry * 1.02
        add_signal(s['symbol'], side, entry, sl, tp, s['asset_type'])

# ------------------------------
# Bot Main Loop
# ------------------------------
def start_bot():
    if client is None:
        logging.warning("Bot running in offline/dry mode.")
    else:
        logging.info("Bot running with live Coinbase connection.")

    while True:
        # 1. Generate new signals
        generate_nija_signals()

        # 2. Process signals
        signals = fetch_signals()
        for signal in signals:
            if signal['status'] == 'pending':
                size = calculate_position_size(signal)
                execute_trade(signal, size)
            if signal['status'] == 'open':
                update_trailing_stop(signal)
                update_trailing_take_profit(signal)
        
        logging.info("Bot heartbeat...")
        time.sleep(60)  # adjust frequency as needed

# ------------------------------
# Run Bot
# ------------------------------
if __name__ == "__main__":
    start_bot()
