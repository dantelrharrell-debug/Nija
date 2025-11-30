# wsgi.py
from nija_coinbase import test_coinbase_connection

# Run Coinbase test on container startup
test_coinbase_connection()

from flask import Flask  # or whatever your app uses
app = Flask(__name__)

@app.route("/")
def index():
    return "NIJA Bot is running!"

# nija_bot.py
import os
import logging
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger()

logger.info("=== STARTING NIJA TRADING BOT ===")

# Attempt to import Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logger.error("coinbase_advanced module not installed. Live trading disabled.")

# Connect to Coinbase
def connect_coinbase():
    if Client is None:
        logger.error("Coinbase client not available.")
        return None
    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        account = client.get_account()
        logger.info(f"Coinbase connection successful. Account ID: {account['id']}")
        return client, account
    except Exception as e:
        logger.error(f"Coinbase connection failed: {e}")
        return None, None

# Simple live trading loop
def live_trading_loop(client, account):
    logger.info("=== STARTING LIVE TRADING LOOP ===")
    while True:
        try:
            # Example: check account balance
            balance = client.get_account_balance(account['id'])
            logger.info(f"Account balance: {balance}")

            # Example trade logic (replace with your actual strategy)
            # WARNING: This will execute real trades if configured
            if float(balance) > 10:  # minimal balance threshold
                order = client.place_order(
                    account_id=account['id'],
                    side='buy',
                    product_id='BTC-USD',
                    size='0.001',  # small test trade
                    type='market'
                )
                logger.info(f"Trade executed: {order}")
            else:
                logger.info("Balance too low to place trade.")

            # Wait before next check (adjust to your strategy)
            time.sleep(10)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(10)  # retry after delay

# Main startup
if __name__ == "__main__":
    client, account = connect_coinbase()
    if client and account:
        live_trading_loop(client, account)
    else:
        logger.error("Cannot start trading loop without a valid Coinbase connection.")

# Minimal WSGI app for container healthcheck
def app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    if Client:
        return [b"NIJA Bot running and ready for live trading.\n"]
    else:
        return [b"NIJA Bot running but NOT connected to Coinbase.\n"]
