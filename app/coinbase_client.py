import os
import logging
import threading
import time

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")

# ----------------------------
# Coinbase Client Setup
# ----------------------------
def get_coinbase_client():
    if Client is None:
        return None
    
    return Client(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_sub=os.environ.get("COINBASE_API_SUB")
    )

# ----------------------------
# Live Trading Loop (stub)
# ----------------------------
def live_trading_loop():
    client = get_coinbase_client()
    if client is None:
        logging.warning("Coinbase client unavailable. Live trading disabled.")
        return

    logging.info("Starting live trading loop...")
    
    try:
        while True:
            # Example: Fetch BTC-USD ticker
            try:
                ticker = client.get_ticker(product_id="BTC-USD")
                logging.info(f"[Ticker] BTC-USD: {ticker['price']}")
            except Exception as e:
                logging.error(f"Error fetching ticker: {e}")
            
            # TODO: Add strategy here (e.g., enter/exit trades)
            time.sleep(5)  # 5-second interval between updates
    except Exception as e:
        logging.error(f"Trading loop crashed: {e}")
    finally:
        logging.info("Live trading loop terminated.")

# ----------------------------
# Run trading loop in background
# ----------------------------
def start_trading_thread():
    thread = threading.Thread(target=live_trading_loop, daemon=True)
    thread.start()
