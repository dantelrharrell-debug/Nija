def decide_trade(client):
    """
    Simple example strategy:
    Buy BTC if USD balance >= $10
    """
    balances = client.get_account_balances()
    usd_balance = float(balances.get("USD", 0))
    if usd_balance >= 10:
        return {"action":"buy","product_id":"BTC-USD","confidence":1.0}
    return None
