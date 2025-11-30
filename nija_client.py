# nija_client.py
import os
import logging
import time
from decimal import Decimal

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ----------------------------
# Coinbase connection
# ----------------------------
try:
    from coinbase_advanced.client import Client

    client = Client(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_sub=os.environ.get("COINBASE_API_SUB")
    )

    # Test connection
    account = client.get_account()
    logging.info(f"✅ Coinbase connection successful. Account ID: {account['id']}")

except ModuleNotFoundError:
    client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")
except Exception as e:
    client = None
    logging.error(f"❌ Coinbase connection failed: {e}")

# ----------------------------
# NIJA Signal Logic Placeholder
# ----------------------------
# Replace this function with your full NIJA logic
def generate_nija_signals():
    """
    Return a list of trade signals.
    Each signal should be a dict:
    {
        'symbol': 'BTC-USD',
        'side': 'buy' or 'sell',
        'type': 'spot'/'crypto'/'stock'/'options'/'futures',
        'quantity': 0.01,
        'price': None,  # optional for market orders
        'trail_sl': 0.02,  # trailing stop loss 2%
        'trail_tp': 0.03   # trailing take profit 3%
    }
    """
    # Example static signal
    return [
        {
            'symbol': 'BTC-USD',
            'side': 'buy',
            'type': 'crypto',
            'quantity': 0.001,
            'price': None,
            'trail_sl': 0.02,
            'trail_tp': 0.03
        }
    ]

# ----------------------------
# Order execution
# ----------------------------
def place_order(signal):
    if client is None:
        logging.warning(f"Dry run: {signal['side']} {signal['quantity']} {signal['symbol']}")
        return None

    try:
        order = client.create_order(
            product_id=signal['symbol'],
            side=signal['side'],
            size=signal['quantity'],
            type='market' if signal['price'] is None else 'limit',
            price=signal['price']
        )
        logging.info(f"✅ Order placed: {signal['side']} {signal['quantity']} {signal['symbol']} @ {signal['price']}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order: {e}")
        return None

# ----------------------------
# Trailing Stop / Take Profit
# ----------------------------
def monitor_trailing(order, trail_sl, trail_tp):
    if client is None or order is None:
        return
    try:
        symbol = order['product_id']
        side = order['side']
        filled_price = Decimal(order['filled_avg_price'])
        logging.info(f"Starting trailing monitor for {symbol} @ {filled_price}")

        # Placeholder logic for trailing
        while True:
            market_price = Decimal(client.get_ticker(symbol)['price'])
            
            # Trailing Stop Loss
            if side == 'buy':
                if market_price <= filled_price * (1 - Decimal(trail_sl)):
                    logging.info(f"Trigger trailing SL: sell {symbol} at {market_price}")
                    client.create_order(
                        product_id=symbol,
                        side='sell',
                        size=order['filled_size'],
                        type='market'
                    )
                    break
            elif side == 'sell':
                if market_price >= filled_price * (1 + Decimal(trail_sl)):
                    logging.info(f"Trigger trailing SL: buy {symbol} at {market_price}")
                    client.create_order(
                        product_id=symbol,
                        side='buy',
                        size=order['filled_size'],
                        type='market'
                    )
                    break

            # Trailing Take Profit
            if side == 'buy':
                if market_price >= filled_price * (1 + Decimal(trail_tp)):
                    logging.info(f"Trigger trailing TP: sell {symbol} at {market_price}")
                    client.create_order(
                        product_id=symbol,
                        side='sell',
                        size=order['filled_size'],
                        type='market'
                    )
                    break
            elif side == 'sell':
                if market_price <= filled_price * (1 - Decimal(trail_tp)):
                    logging.info(f"Trigger trailing TP: buy {symbol} at {market_price}")
                    client.create_order(
                        product_id=symbol,
                        side='buy',
                        size=order['filled_size'],
                        type='market'
                    )
                    break

            time.sleep(5)  # check every 5 seconds

    except Exception as e:
        logging.error(f"Error in trailing monitor: {e}")

# ----------------------------
# Bot loop
# ----------------------------
def start_bot():
    if client is None:
        logging.warning("Bot running in dry/offline mode.")
    else:
        logging.info("Bot running LIVE 24/7 with Coinbase connection.")

    while True:
        try:
            signals = generate_nija_signals()
            for signal in signals:
                order = place_order(signal)
                if order:
                    monitor_trailing(order, signal['trail_sl'], signal['trail_tp'])
            logging.info("✅ Bot heartbeat complete. Waiting 60s for next cycle.")
            time.sleep(60)
        except Exception as e:
            logging.error(f"Bot runtime error: {e}")
            time.sleep(60)

# ----------------------------
# Entry point
# ----------------------------
if __name__ == "__main__":
    start_bot()
