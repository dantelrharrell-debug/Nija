# nija_client.py
from coinbase_advanced_py import Client

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase, api_sub):
        self.client = Client(
            api_key=api_key,
            api_secret_path=api_secret_path,
            api_passphrase=api_passphrase,
            api_sub=api_sub
        )

    def create_order(self, product_id, side, type, size):
        """
        Execute a market order via Coinbase Advanced API
        """
        return self.client.rest.place_order(
            product_id=product_id,
            side=side,
            type=type,
            size=size
        )
