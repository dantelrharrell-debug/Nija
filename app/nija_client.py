# nija_client.py
from coinbase_advanced import Client

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase, api_sub):
        """
        Initializes the Coinbase client.
        """
        self.client = Client(
            key=api_key,
            secret_path=api_secret_path,
            passphrase=api_passphrase,
            sub=api_sub
        )

    def create_order(self, product_id, side, type="market", size="0.001"):
        """
        Places a market order on Coinbase.
        """
        return self.client.create_order(
            product_id=product_id,
            side=side,
            type=type,
            size=size
        )
