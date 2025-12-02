import logging
from decimal import Decimal
from time import sleep

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Position sizing
MIN_ALLOCATION = Decimal("0.02")  # 2% of account equity
MAX_ALLOCATION = Decimal("0.10")  # 10% of account equity

# Example signal functions (replace with your real trading logic)
def get_market_signal():
    """
    Return 'BUY', 'SELL', or None based on your strategy.
    Example: VWAP, RSI, or any indicator.
    """
    # Placeholder logic
    return "BUY"  # always buys for demo purposes

def get_usd_balance(client) -> Decimal:
    try:
        accounts = client.get_accounts()
        for acc in accounts['data']:
            if acc['currency'] == 'USD':
                balance = Decimal(acc['balance']['amount'])
                logger.info(f"USD Balance: ${balance}")
                return balance
        logger.warning("USD account not found.")
        return Decimal(0)
    except Exception as e:
        logger.error(f"Failed to fetch account balance: {e}")
        return Decimal(0)

def calculate_order_size(balance: Decimal, allocation_pct: Decimal = MIN_ALLOCATION) -> Decimal:
    allocation = balance * allocation_pct
    logger.info(f"Allocating ${allocation} for this trade ({allocation_pct*100}%)")
    return allocation

def place_live_order(client, buy_currency="BTC-USD", allocation_pct: Decimal = MIN_ALLOCATION):
    balance = get_usd_balance(client)
    if balance <= 0:
        logger.error("No USD available to place an order.")
        return None

    allocation_pct = max(MIN_ALLOCATION, min(MAX_ALLOCATION, allocation_pct))
    order_amount = calculate_order_size(balance, allocation_pct)

    try:
        order = client.buy(
            buy_currency,
            total=str(round(order_amount, 2)),  # Coinbase expects string with 2 decimal places
            currency="USD"
        )
        logger.info(f"Live order executed successfully: {order}")
        return order
    except Exception as e:
        logger.error(f"Failed to place live order: {e}")
        return None

# ====== Main loop ======
def run_live_trading(client):
    logger.info("Starting live trading loop...")
    while True:
        signal = get_market_signal()
        if signal == "BUY":
            place_live_order(client, buy_currency="BTC-USD", allocation_pct=Decimal("0.05"))
        elif signal == "SELL":
            # Add your sell logic here (optional)
            logger.info("Signal SELL received. Implement sell logic if needed.")
        else:
            logger.info("No trade signal detected.")
        sleep(60)  # check every minute (adjust as needed)

# Run only if client initialized
if client:
    run_live_trading(client)
else:
    logger.error("Coinbase client not initialized. Exiting.")
