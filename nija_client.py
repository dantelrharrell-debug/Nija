"""
nija_client - now wired to coinbase_adapter for robust detection.

This wrapper exposes:
- fetch_accounts()
- fetch_open_orders()
- fetch_fills(product_id=None)
- place_market_order(product_id, side, size)

It uses coinbase_adapter.create_adapter(...) to instantiate a normalized adapter around
any detected Coinbase client (cbpro, coinbase, coinbase.wallet, or coinbase_advanced if available).
"""
import os
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija_client")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

try:
    from coinbase_adapter import create_adapter  # runtime import
except Exception:
    create_adapter = None


class CoinbaseClient:
    def __init__(self):
        logger.info("nija_client startup: loading Coinbase auth config")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

        jwt_set = bool(self.pem_content)
        api_key_set = bool(self.api_key)
        org_id_set = bool(self.org_id)

        logger.info(f" - base={self.base_url}")
        logger.info(f" - advanced=True")
        logger.info(f" - jwt_set={'yes' if jwt_set else 'no'}")
        logger.info(f" - api_key_set={'yes' if api_key_set else 'no'}")
        logger.info(f" - api_passphrase_set={'yes' if bool(self.passphrase) else 'no'}")
        logger.info(f" - org_id_set={'yes' if org_id_set else 'no'}")
        logger.info(f" - private_key_path_set=no")

        self.adapter = None
        if create_adapter:
            try:
                self.adapter = create_adapter(self.api_key, self.api_secret, self.passphrase, self.pem_content, self.org_id, self.base_url)
                logger.info(f"nija_client: adapter client_name={getattr(self.adapter, 'client_name', None)}")
            except Exception:
                logger.exception("nija_client: create_adapter raised an exception")
                self.adapter = None
        else:
            logger.info("nija_client: create_adapter not available; operations will no-op")

        # Connection check (only log verified if accounts actually present)
        try:
            accounts = self.fetch_accounts()
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                logger.info("🔹 Coinbase connection verified. Accounts fetched.")
            else:
                logger.error("🔹 Coinbase connection failed: unable to fetch accounts (client missing or returned no accounts)")
        except Exception:
            logger.exception("nija_client connection check threw")

    def is_connected(self) -> bool:
        try:
            if not self.adapter or not getattr(self.adapter, "client", None):
                return False
            accounts = self.fetch_accounts()
            return bool(accounts and isinstance(accounts, list) and len(accounts) > 0)
        except Exception:
            return False

    def fetch_accounts(self) -> List[Dict[str, Any]]:
        try:
            if not self.adapter:
                logger.debug("fetch_accounts: no adapter present; returning empty list.")
                return []
            return self.adapter.get_accounts() or []
        except Exception as e:
            logger.exception(f"fetch_accounts exception: {e}")
            return []

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        try:
            if not self.adapter:
                return []
            return self.adapter.get_open_orders() or []
        except Exception as e:
            logger.exception(f"fetch_open_orders exception: {e}")
            return []

    def fetch_fills(self, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            if not self.adapter:
                return []
            return self.adapter.get_fills(product_id) or []
        except Exception as e:
            logger.exception(f"fetch_fills exception: {e}")
            return []

    def place_market_order(self, product_id: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        try:
            if not self.adapter:
                logger.error("place_market_order: no adapter present")
                return None
            return self.adapter.place_market_order(product_id, side, size)
        except Exception as e:
            logger.exception(f"place_market_order exception: {e}")
            return None
