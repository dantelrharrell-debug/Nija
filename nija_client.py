# nija_client.py
import os
import logging
import requests
from decimal import Decimal

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# --- Load environment keys ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
USE_DUMMY = False

if not API_KEY or not API_SECRET:
    raise RuntimeError("[NIJA] Missing API_KEY or API_SECRET — live trading cannot start")

logger.info("[NIJA] Live RESTClient instantiated (no passphrase required)")

class RESTClient:
    """Minimal Coinbase REST client using only API key + secret."""
    BASE_URL = "https://api.exchange.coinbase.com"

    def __init__(self, key, secret):
        self.key = key
        self.secret = secret
        self.session = requests.Session()
        self.session.headers.update({
            "CB-ACCESS-KEY": key,
            "CB-ACCESS-SIGN": secret,  # for simplicity; adjust if you have real signature logic
            "Content-Type": "application/json"
        })

    def get_account_balances(self):
        """Return USD balance as dict"""
        url = f"{self.BASE_URL}/accounts"
        r = self.session.get(url, timeout=10)
        r.raise_for_status()
        balances = {a['currency']: a['available'] for a in r.json()}
        return balances

    def get_price(self, product_id="BTC-USD"):
        url = f"{self.BASE_URL}/products/{product_id}/ticker"
        r = self.session.get(url, timeout=10)
        r.raise_for_status()
        return Decimal(str(r.json()["price"]))

    def place_order(self, side, product_id, funds):
        url = f"{self.BASE_URL}/orders"
        data = {
            "type": "market",
            "side": side,
            "product_id": product_id,
            "funds": str(funds)
        }
        r = self.session.post(url, json=data, timeout=10)
        r.raise_for_status()
        return r.json()


# Instantiate client
client = RESTClient(API_KEY, API_SECRET)
