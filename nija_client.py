# nija_client.py - factory for Coinbase Advanced client
import os
import logging
from time import sleep

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Import after coinbase-advanced installed at runtime
from coinbase_advanced.client import Client

def get_coinbase_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # if used
    org_id = os.getenv("COINBASE_ORG_ID")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")

    if not api_key or not api_secret:
        raise ValueError("Missing COINBASE_API_KEY or COINBASE_API_SECRET")

    client_kwargs = dict(api_key=api_key, api_secret=api_secret)
    if api_passphrase:
        client_kwargs["api_passphrase"] = api_passphrase
    if org_id:
        client_kwargs["api_org_id"] = org_id
    if pem_content:
        # some libs expect bytes
        client_kwargs["pem"] = pem_content.encode()

    client = Client(**client_kwargs)
    logger.info("✅ Coinbase client created")
    return client
