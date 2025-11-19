# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Export the env var name for main.py convenience
COINBASE_ACCOUNT_ID = os.environ.get("COINBASE_ACCOUNT_ID")

def get_coinbase_client():
    """
    Lazily import and return a coinbase_advanced Client instance.
    Raises ValueError if required env vars are missing.
    """
    try:
        # import inside function to avoid ImportError at module load before runtime install
        from coinbase_advanced.client import Client
    except Exception as e:
        logger.exception("coinbase_advanced package not available")
        raise

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE") or os.environ.get("COINBASE_API_PASSPHRASE")  # optional naming
    org_id = os.environ.get("COINBASE_ORG_ID")
    pem_content = os.environ.get("COINBASE_PEM_CONTENT")  # optional if using pem

    missing = [k for k, v in {
        "COINBASE_API_KEY": api_key,
        "COINBASE_API_SECRET": api_secret
    }.items() if not v]

    if missing:
        raise ValueError(f"Missing Coinbase env vars: {missing}")

    # Adapt parameters to the version of the client you have.
    client_kwargs = {
        "api_key": api_key,
        "api_secret": api_secret,
    }
    # optional params
    if api_passphrase:
        client_kwargs["api_passphrase"] = api_passphrase
    if org_id:
        client_kwargs["api_org_id"] = org_id
    if pem_content:
        client_kwargs["pem"] = pem_content.encode()

    client = Client(**client_kwargs)
    logger.info("✅ Coinbase Advanced client created")
    return client
