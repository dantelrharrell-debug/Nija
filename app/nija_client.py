# nija_client.py
from coinbase_advanced_py import CoinbaseAdvanced
import os

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE", "")
        self.live = os.getenv("LIVE_TRADING", "0") == "1"

        self.client = CoinbaseAdvanced(
            api_key=self.api_key,
            api_secret=self.api_secret,
            passphrase=self.passphrase,
            sandbox=not self.live  # sandbox mode unless LIVE_TRADING=1
        )

    def list_accounts(self):
        return self.client.accounts.list()  # returns list of accounts

    def place_market_buy_by_quote(self, product_id, quote_size_usd):
        return self.client.orders.place_market_order(
            product_id=product_id,
            side="BUY",
            quote_size=str(quote_size_usd)
        )
