# src/nija_client.py
import logging
from src import config

# Try to import official Coinbase Advanced SDK (preferred)
try:
    from coinbase_advanced.client import Client as CoinbaseAdvancedClient
    from coinbase_advanced import jwt_generator
    SDK_AVAILABLE = True
except Exception:
    SDK_AVAILABLE = False

class CoinbaseClient:
    def __init__(self):
        if config.LIVE_TRADING:
            if not (config.COINBASE_API_KEY and config.COINBASE_API_SECRET and config.COINBASE_PEM_CONTENT):
                raise RuntimeError("Coinbase credentials required for live trading")
        logging.info("CoinbaseClient initialized (LIVE=%s, SDK_AVAILABLE=%s)", config.LIVE_TRADING, SDK_AVAILABLE)
        self.sdk = None
        if SDK_AVAILABLE:
            # instantiate client if needed per SDK; use JWT per request if required
            self.sdk = CoinbaseAdvancedClient(api_key=config.COINBASE_API_KEY,
                                              api_secret=config.COINBASE_API_SECRET)

    def fetch_accounts(self):
        if self.sdk:
            return self.sdk.accounts.list()  # refer to SDK docs for method name
        # fallback / mock
        return [{"id": "mock", "currency": "USD", "balance": "0.00"}]

    def execute_trade(self, payload):
        """
        Implement this carefully:
         - Validate payload
         - Compute position sizing
         - Use idempotency keys to avoid duplicate orders
         - Log responses and errors
        """
        if not config.LIVE_TRADING:
            logging.info("Test mode: execute_trade called but not running orders.")
            return {"mock": True}
        if not self.sdk:
            raise RuntimeError("Coinbase SDK not available in environment")
        # Example: create order using SDK (replace with actual SDK call)
        # order = self.sdk.orders.create(...)
        # return order
        raise NotImplementedError("Implement order placement via SDK here")
