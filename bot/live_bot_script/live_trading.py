# bot/live_bot_script/live_trading.py
import logging
import time

logger = logging.getLogger(__name__)

def run_live_trading(client):
    """
    Run live trading loop safely.
    Places a minimal $1 order once on startup, then continues normal trading.
    """
    try:
        # 1️⃣ Check account balances
        accounts = client.get_accounts()
        usd_account = next((a for a in accounts if a['currency'] == 'USD'), None)

        if not usd_account:
            logger.error("No USD account found. Cannot place live orders.")
            return

        usd_balance = float(usd_account['balance']['amount'])
        logger.info(f"USD Balance: ${usd_balance:.2f}")

        # 2️⃣ Place minimal order ONCE
        minimal_order_amount = 1.00  # $1 trade
        if usd_balance >= minimal_order_amount:
            order = client.place_order(
                product_id='BTC-USD',
                side='buy',
                type='market',
                funds=str(minimal_order_amount)  # amount in USD
            )
            logger.info(f"✅ First minimal live order placed: {order}")
        else:
            logger.warning(f"Insufficient balance for minimal order (${minimal_order_amount}).")

        # 3️⃣ Main live trading loop (replace with your real strategy)
        logger.info("Starting main live trading loop...")
        while True:
            # Example: heartbeat log
            logger.info("Live trading heartbeat... waiting for next iteration.")
            time.sleep(60)  # adjust interval as needed

    except Exception as e:
        logger.error(f"Error in live trading: {e}")
