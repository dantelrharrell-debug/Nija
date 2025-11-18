import logging

try:
    from coinbase_advanced_py.rest_client import RestClient
except ImportError as e:
    logging.error(f"❌ Coinbase Advanced SDK not installed: {e}")
    RestClient = None

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase="", api_sub=None):
        if RestClient is None:
            raise ImportError("Coinbase Advanced SDK not available")

        self.api_key = api_key
        self.api_secret_path = api_secret_path
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        self.client = self._init_client()

    def _init_client(self):
        try:
            client = RestClient(
                api_key=self.api_key,
                secret_path=self.api_secret_path,
                passphrase=self.api_passphrase,
                sub=self.api_sub
            )
            logging.info("✅ Coinbase client initialized")
            return client
        except FileNotFoundError:
            logging.error(f"❌ PEM file not found: {self.api_secret_path}")
            raise
        except Exception as e:
            logging.error(f"❌ Failed to initialize Coinbase client: {e}")
            raise

    def create_order(self, product_id, side, type, size):
        return self.client.create_order(
            product_id=product_id,
            side=side,
            type=type,
            size=size
        )
