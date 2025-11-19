# nija_client.py
import os
import logging
import time
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

def install_and_import():
    """Attempt to import Client; if missing, raise so calling script can install at runtime."""
    try:
        from coinbase_advanced.client import Client
        return Client
    except Exception as e:
        logger.error("coinbase_advanced not available (import failed).")
        raise

def get_coinbase_client(retries: int = 3, delay: float = 2.0):
    Client = install_and_import()
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")
    org_id = os.getenv("COINBASE_ORG_ID")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")  # optional

    if not all([api_key, api_secret]):
        raise ValueError("Missing COINBASE_API_KEY or COINBASE_API_SECRET")

    # Attempt initialization (some installs accept different kwargs)
    for attempt in range(1, retries+1):
        try:
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase if api_passphrase else None,
                api_org_id=org_id if org_id else None,
                pem=pem_content.encode() if pem_content else None
            )
            logger.info("✅ Coinbase client initialized")
            return client
        except TypeError:
            # fallback parameter names if the SDK uses different names
            client = Client(api_key=api_key, api_secret=api_secret)
            logger.info("✅ Coinbase client initialized with fallback args")
            return client
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed to init Coinbase client: {e}")
            time.sleep(delay)
    raise RuntimeError("Failed to initialize Coinbase client after retries")
