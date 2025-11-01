# nija_balance_helper.py
from decimal import Decimal
from coinbase.rest import RESTClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# Initialize REST client with your API key/secret
client = RESTClient(
    api_key="YOUR_API_KEY_HERE",
    api_secret="YOUR_API_SECRET_HERE"
)

def get_usd_balance():
    """
    Fetch USD balance from all Coinbase accounts accessible via this API key.
    Returns Decimal(0) if no USD found or API fails.
    """
    try:
        accounts = client.get_accounts()
        total_usd = Decimal(0)
        logger.info("[NIJA-BALANCE] Scanning Coinbase accounts for USD...")

        for a in accounts['data']:
            name = a.get('name', 'Unknown')
            currency = a['balance']['currency']
            balance = Decimal(a['balance']['amount'])
            logger.info(f"[NIJA-BALANCE] Account: {name}, Balance: {balance} {currency}")

            if currency.upper() == "USD":
                total_usd += balance

        if total_usd > 0:
            logger.info(f"[NIJA-BALANCE] Total USD balance detected: {total_usd}")
            return total_usd
        else:
            logger.warning("[NIJA-BALANCE] No USD balance found, returning 0")
            return Decimal(0)

    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch balance: {e}")
        return Decimal(0)

# Test script
if __name__ == "__main__":
    usd = get_usd_balance()
    print(f"Detected USD balance: {usd}")
