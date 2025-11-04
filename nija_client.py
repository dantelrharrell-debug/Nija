# nija_client.py
import os
from coinbase.wallet.client import Client
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")


def get_coinbase_client():
    """
    Initializes Coinbase Client from environment variables.
    """
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional if not needed

    if not api_key or not api_secret:
        log.error("Missing Coinbase API credentials in environment variables.")
        raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

    # Handle multi-line secret if pasted with literal \n
    if "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")

    client = Client(api_key, api_secret)
    log.info("Coinbase client initialized successfully.")
    return client


def get_usd_spot_balance(client=None):
    """
    Fetches USD spot balance from Coinbase account.
    Returns a float (0 if fetch fails).
    """
    if client is None:
        client = get_coinbase_client()

    try:
        accounts = client.get_accounts()
        for acc in accounts['data']:
            if acc['balance']['currency'] == "USD":
                return float(acc['balance']['amount'])
        log.warning("No USD balance found in accounts.")
        return 0.0
    except Exception as e:
        log.error(f"Error fetching USD balance: {type(e).__name__} {e}")
        return 0.0
