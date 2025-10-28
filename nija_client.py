#!/usr/bin/env python3
# nija_client.py
import os
import logging
from decimal import Decimal
from coinbase_advanced_py.client.client import CoinbaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# -------------------------------
# Coinbase client initialization
# -------------------------------
try:
    client = CoinbaseClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        passphrase=os.environ.get("COINBASE_PASSPHRASE")  # optional
    )
    logger.info("✅ Coinbase client initialized successfully.")
except KeyError as e:
    logger.error(f"Missing environment variable: {e}")
    raise SystemExit(1)
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    raise SystemExit(1)

# -------------------------------
# Helper functions
# -------------------------------
def get_accounts():
    try:
        accounts = client.get_accounts()
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return []

def place_order(symbol: str, side: str, amount: Decimal):
    try:
        order = client.place_order(
            product_id=symbol,
            side=side,
            size=str(amount)
        )
        logger.info(f"Order placed: {order}")
        return order
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        return None
