import time
import logging
from nija_client import CoinbaseClient  # your working Coinbase client

# --- Initialize Coinbase client ---
coinbase_client = CoinbaseClient(
    api_key="YOUR_API_KEY",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",  # usually empty for Advanced API
    api_sub="YOUR_ACCOUNT_SUB_ID",  # your funded account
)

# --- Trading configuration ---
LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds between signal checks
MIN_POS_PCT = 0.02   # minimum 2% of account balance per trade
MAX_POS_PCT = 0.10   # maximum 10% of account balance per trade

# --- Your trading signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy"},
    {"symbol": "BTC-USD", "side": "sell"},
    {"symbol": "ETH-USD", "side": "buy"},
    {"symbol": "ETH-USD", "side": "sell"},
]

def get_account_balance(symbol: str):
    """
    Fetch account balance for the given currency.
    """
    try:
        balances = coinbase_client.get_accounts()
        # Look for USD or crypto balance
        for acc in balances:
            if acc['currency'] in symbol:  # BTC-USD -> BTC
                return float(acc['available'])
            elif acc['currency'] == 'USD' and 'USD' in symbol:
                return float(acc['available'])
        return 0.0
    except Exception as e:
        logging.error(f"❌ Failed to fetch account balance: {e}")
        return 0.0

def calculate_order_size(symbol: str):
    """
    Calculate trade size based on account balance and min/max limits.
    """
    balance = get_account_balance(symbol)
    position = balance * MAX_POS_PCT  # adjust to max 10%
    return round(position, 8)  # round for crypto precision

def check_signals():
    return TRADING_SIGNALS

def place_order(symbol: str, side: str):
    """
    Execute a live order with safe position sizing.
    """
    global coinbase_client
    size = calculate_order_size(symbol)

    if size <= 0:
        logging.warning(f"⚠️ Not enough balance to trade {symbol}")
        return None

    if not LIVE_TRADING:
        logging.info(f"💡 Dry run: {side} {size} {symbol}")
        return None

    try:
        order = coinbase_client.create_order(
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)
        )
        logging.info(f"✅ Order executed: {side} {size} {symbol} | ID: {order.get('id')}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order {side} {size} {symbol}: {e}")
        return None

def trading_loop():
    logging.info("🚀 Starting live trading loop...")
    while True:
        signals = check_signals()
        for signal in signals:
            symbol = signal.get("symbol")
            side = signal.get("side")
            if symbol and side:
                place_order(symbol, side)
            else:
                logging.warning(f"⚠️ Incomplete signal skipped: {signal}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
