# --- Load bot configuration ---
LIVE_TRADING = int(os.environ.get("LIVE_TRADING", 0))
MIN_TRADE_PERCENT = float(os.environ.get("MIN_TRADE_PERCENT", 2)) / 100
MAX_TRADE_PERCENT = float(os.environ.get("MAX_TRADE_PERCENT", 10)) / 100
BOT_SECRET_KEY = os.environ.get("BOT_SECRET_KEY")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# --- Utility: Calculate dynamic trade size ---
def calculate_trade_size(account_balance, risk_percent=None):
    """
    account_balance: float, total funds in account
    risk_percent: optional, override default min/max percent
    Returns: trade size (float)
    """
    if risk_percent:
        trade_percent = max(MIN_TRADE_PERCENT, min(MAX_TRADE_PERCENT, risk_percent))
    else:
        trade_percent = MAX_TRADE_PERCENT  # default to max percent
    size = account_balance * trade_percent
    return round(size, 8)  # round to 8 decimals for crypto

# --- Example usage in place_order ---
def place_dynamic_order(account_id, side, product_id, balance=None, risk_percent=None):
    """
    Places a market order based on dynamic position sizing.
    balance: account balance in USD (or quote currency)
    risk_percent: optional override for trade percent
    """
    if balance is None:
        accounts = get_accounts()
        if accounts and "data" in accounts:
            for acc in accounts["data"]:
                if acc["id"] == account_id:
                    balance = float(acc["balance"]["amount"])
                    break
        if balance is None:
            logger.error(f"Could not retrieve balance for account {account_id}")
            return None

    trade_size = calculate_trade_size(balance, risk_percent)
    logger.info(f"Placing {side} order of size {trade_size} on {product_id}")
    return place_order(account_id, side, str(trade_size), product_id)

# --- Example testing ---
if __name__ == "__main__":
    accounts = get_accounts()
    if accounts and len(accounts.get("data", [])) > 0:
        first_account_id = accounts["data"][0]["id"]
        balance = float(accounts["data"][0]["balance"]["amount"])
        logger.info(f"Account balance: {balance}")

        # Place a dynamic BTC-USD buy order
        result = place_dynamic_order(first_account_id, "buy", "BTC-USD", balance)
        logger.info(result)
