import os
import json
import logging
import time
from coinbase.rest import RESTClient  # Official Coinbase REST client

logger = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        logger.info("nija_client startup: loading Coinbase auth config")

        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")

        self.base_url = "https://api.coinbase.com"
        self.advanced = True

        jwt_set = bool(self.pem)
        api_key_set = bool(self.api_key)
        org_id_set = bool(self.org_id)

        logger.info(f" - base={self.base_url}")
        logger.info(f" - advanced={self.advanced}")
        logger.info(f" - jwt_set={'yes' if jwt_set else 'no'}")
        logger.info(f" - api_key_set={'yes' if api_key_set else 'no'}")
        logger.info(f" - api_passphrase_set=no")
        logger.info(f" - org_id_set={'yes' if org_id_set else 'no'}")
        logger.info(f" - private_key_path_set=no")

        # Create Coinbase Advanced REST client
        if jwt_set:
            self.client = RESTClient(
                key=self.api_key,
                secret=self.api_secret,
                passphrase="",
                base_url=self.base_url,
                # JWT auth
                pem=self.pem,
                org_id=self.org_id,
            )
        else:
            self.client = RESTClient(
                key=self.api_key,
                secret=self.api_secret,
                passphrase="",
                base_url=self.base_url,
            )

        logger.success("Found at least one authentication method (JWT or API key/secret).")

    # ============================================================
    #                   PUBLIC ACCOUNT METHODS
    # ============================================================
    def fetch_accounts(self):
        """Return all Coinbase Advanced accounts."""
        try:
            resp = self.client.get_accounts()
            return resp["accounts"]
        except Exception as e:
            logger.error(f"❌ fetch_accounts() failed: {e}")
            return []

    def fetch_open_orders(self):
        """Return all open orders."""
        try:
            resp = self.client.get_orders(status="OPEN")
            return resp["orders"]
        except Exception as e:
            logger.error(f"❌ fetch_open_orders() failed: {e}")
            return []

    def fetch_fills(self, product_id=None):
        """Return recent fills (executed trades)."""
        try:
            if product_id:
                resp = self.client.get_fills(product_id=product_id)
            else:
                resp = self.client.get_fills()

            return resp["fills"]
        except Exception as e:
            logger.error(f"❌ fetch_fills() failed: {e}")
            return []

    # ============================================================
    #                   PLACE ORDER
    # ============================================================
    def place_market_order(self, product_id, side, size):
        try:
            order = {
                "product_id": product_id,
                "side": side,
                "order_configuration": {
                    "market_market_ioc": {
                        "base_size": str(size)
                    }
                }
            }
            resp = self.client.create_order(order)
            return resp
        except Exception as e:
            logger.error(f"❌ place_market_order() failed: {e}")
            return None
