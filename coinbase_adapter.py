# coinbase_adapter.py (replace or patch create_adapter)
import logging, os

LOG = logging.getLogger(__name__)

def create_adapter():
    # Try coinbase_advanced (if you vendored or installed it)
    try:
        from coinbase_advanced.client import Client as AdvancedClient
        LOG.info("Using coinbase_advanced client")
        client = AdvancedClient()  # pass config if your lib requires it
        return {"client_name": "coinbase_advanced", "client": client}
    except Exception:
        LOG.info("coinbase_advanced not available or failed to import")

    # Try official coinbase wallet client (legacy)
    try:
        from coinbase.wallet.client import Client as WalletClient
        api_key = os.getenv("COINBASE_API_KEY")
        api_secret = os.getenv("COINBASE_API_SECRET")
        if api_key and api_secret:
            client = WalletClient(api_key=api_key, api_secret=api_secret)
            LOG.info("Using coinbase.wallet.client")
            return {"client_name": "coinbase.wallet.client", "client": client}
        else:
            LOG.info("Legacy coinbase client present but API key/secret missing")
    except Exception:
        LOG.info("legacy coinbase client import failed")

    LOG.info("no supported Coinbase client library found; returning adapter with client=None")
    return {"client_name": "none", "client": None}
