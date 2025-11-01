# nija_balance_helper.py (debug version)
from decimal import Decimal
from coinbase.rest import RESTClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

client = RESTClient(api_key="YOUR_API_KEY_HERE", api_secret="YOUR_API_SECRET_HERE")

def get_usd_balance():
    """
    Fetch USD balance from all Coinbase accounts.
    Returns Decimal(0) if no USD found or API fails.
    """
    try:
        accounts = client.get_accounts()
        found_usd = Decimal(0)
        for a in accounts['data']:
            name = a['name']
            balance = Decimal(a['balance']['amount'])
            currency = a['balance']['currency']
            logger.info(f"[NIJA-BALANCE] Account: {name}, Balance: {balance} {currency}")
            if currency == "USD":
                found_usd += balance
        
        if found_usd == 0:
            logger.warning("[NIJA-BALANCE] No USD balance found, returning 0")
        return found_usd

    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch balance: {e}")
        return Decimal(0)

if __name__ == "__main__":
    usd = get_usd_balance()
    print(f"Detected USD balance: {usd}")
