import os
import logging
from decimal import Decimal
from coinbase_advanced_py.client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

PEM_PATH = "/opt/render/project/secrets/coinbase.pem"

def get_client():
    try:
        pem_content = os.environ.get("COINBASE_PEM_CONTENT")
        if pem_content:
            os.makedirs(os.path.dirname(PEM_PATH), exist_ok=True)
            with open(PEM_PATH, "w") as f:
                f.write(pem_content)

        client = CoinbaseClient(
            key=os.environ.get("COINBASE_API_KEY"),
            secret=os.environ.get("COINBASE_API_SECRET"),
            passphrase=os.environ.get("COINBASE_API_PASSPHRASE"),
            pem_path=PEM_PATH
        )
        logger.info("[NIJA] Coinbase RESTClient initialized successfully")
        return client

    except Exception as e:
        logger.warning(f"[NIJA] CoinbaseClient unavailable: {e}")
        return None

def get_usd_balance(client):
    accounts = client.get_accounts()
    for acct in accounts:
        if acct['currency'] == 'USD':
            return Decimal(acct['available'])
    return Decimal(0)

def execute_trade(client, amount_usd, product="BTC-USD"):
    # Example: Market buy order
    size = round(amount_usd / float(client.get_spot_price(product)), 8)
    order = client.place_order(product_id=product, side="buy", type="market", size=size)
    return order
