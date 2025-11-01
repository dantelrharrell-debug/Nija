# nija_balance_helper.py
from decimal import Decimal
import logging
from coinbase_advanced_py.client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"
API_PASSPHRASE = "YOUR_API_PASSPHRASE"

client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)

def get_usd_balance():
    try:
        accounts = client.get_accounts()  # or whatever method CoinbaseClient uses
        for a in accounts:
            if a['currency'] == "USD":
                return Decimal(a['balance'])
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed: {e}")
        return Decimal(0)
