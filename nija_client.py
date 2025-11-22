import logging

logger = logging.getLogger(__name__)

class CoinbaseClient:
    """
    Wrapper to unify different Coinbase client libraries.
    Tries multiple clients in order: coinbase_advanced, cbpro, coinbase.
    Defensive: if no client is available, operations safely no-op.
    """
    def __init__(self, api_key=None, api_secret=None, passphrase=None, org_id=None, private_key_path=None, jwt=None):
        self.client = None
        self.client_type = None

        # Try coinbase_advanced
        try:
            from coinbase_advanced.client import Client as AdvancedClient
            self.client = AdvancedClient(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=passphrase,
                org_id=org_id,
                private_key_path=private_key_path,
                jwt=jwt
            )
            self.client_type = 'coinbase_advanced'
            logger.info("Using coinbase_advanced client")
        except ImportError:
            logger.debug("coinbase_advanced not available")

        # Try cbpro
        if self.client is None:
            try:
                import cbpro
                auth_client = cbpro.AuthenticatedClient(api_key, api_secret, passphrase)
                self.client = auth_client
                self.client_type = 'cbpro'
                logger.info("Using cbpro client")
            except ImportError:
                logger.debug("cbpro not available")

        # Try coinbase official package
        if self.client is None:
            try:
                from coinbase.wallet.client import Client as CoinbaseOfficialClient
                self.client = CoinbaseOfficialClient(api_key, api_secret)
                self.client_type = 'coinbase'
                logger.info("Using coinbase official client")
            except ImportError:
                logger.debug("coinbase official client not available")

        if self.client is None:
            logger.warning("No supported Coinbase client found. Operations will safely no-op.")

    def fetch_accounts(self):
        """Return account info, or empty list if client unavailable."""
        if self.client is None:
            return []

        try:
            if self.client_type == 'coinbase_advanced':
                return self.client.get_accounts()
            elif self.client_type == 'cbpro':
                return self.client.get_accounts()
            elif self.client_type == 'coinbase':
                return self.client.get_accounts()['data']
        except Exception as e:
            logger.error(f"Failed to fetch accounts from {self.client_type}: {e}")
            return []

# Example initialization
if __name__ == "__main__":
    import os

    client = CoinbaseClient(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        passphrase=os.environ.get("COINBASE_API_PASSPHRASE"),
        org_id=os.environ.get("COINBASE_ORG_ID"),
        private_key_path=os.environ.get("COINBASE_PRIVATE_KEY_PATH"),
        jwt=os.environ.get("COINBASE_JWT")
    )

    accounts = client.fetch_accounts()
    logger.info(f"Accounts fetched: {accounts}")
