# trading_logic.py

def decide_trade(client):
    """
    Simple live buy/sell logic for BTC-USD:
    - Buy if USD balance >= $10
    - Sell if BTC balance >= 0.001
    - Returns trade signal: {'action':'buy'/'sell', 'product_id':'BTC-USD', 'confidence':0.8}
    """
    try:
        balances = client.get_account_balances()
        usd_balance = float(balances.get("USD", 0))
        btc_balance = float(balances.get("BTC", 0))  # adjust if your client uses a different key

        # Buy logic
        if usd_balance >= 10:
            return {"action": "buy", "product_id": "BTC-USD", "confidence": 1.0}

        # Sell logic
        elif btc_balance >= 0.001:
            return {"action": "sell", "product_id": "BTC-USD", "confidence": 1.0}

    except Exception as e:
        print(f"[TRADING_LOGIC] Error fetching balances: {e}")

    # No trade
    return None
