# nija_bot_web/position_manager.py

def get_trade_allocation(account_balance, desired_percent=0.05):
    """
    Returns trade allocation based on account balance and auto-scaling rules.
    """
    if account_balance < 50:
        if account_balance < 10:
            allocation = 1
        elif account_balance < 25:
            allocation = max(1, min(account_balance * desired_percent, 2.5))
        else:
            allocation = max(2, min(account_balance * desired_percent, 5))
    else:
        allocation = max(account_balance * 0.02, min(account_balance * desired_percent, account_balance * 0.10))
    return round(allocation, 2)
