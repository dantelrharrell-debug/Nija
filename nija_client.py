# start_bot_main.py

import os
import time
from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error(f"Failed to initialize CoinbaseClient: {e}")
        return

    try:
        # --- Get accounts ---
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")

        # Grab first account ID for demo trades
        if not accounts or len(accounts) == 0:
            logger.error("No accounts found, cannot continue")
            return

        account_id = accounts[0]["id"]
        logger.info(f"Using account_id={account_id}")

        # --- Get positions ---
        positions = client.get_positions()
        logger.info(f"Positions fetched: {positions}")

        # --- Demo: Place a market order ---
        # Example: Buy 0.001 BTC-USD (update size/product_id as needed)
        side = "buy"
        product_id = "BTC-USD"
        size = "0.001"

        logger.info(f"Placing order: {side} {size} {product_id}")
        order = client.place_order(account_id, side, product_id, size)
        logger.info(f"Order response: {order}")

        # --- Fetch the order status ---
        order_id = order.get("id")
        if order_id:
            status = client.get_order(order_id)
            logger.info(f"Order status: {status}")
        else:
            logger.warning("No order ID returned, cannot fetch status")

    except Exception as e:
        logger.error(f"Error during bot run: {e}")

if __name__ == "__main__":
    main()
