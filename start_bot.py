import os
from loguru import logger
from decimal import Decimal
from nija_client import NijaCoinbaseClient
from nija_balance_helper import get_usd_balance

# --- Logger setup ---
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

logger.info("Starting Nija Coinbase Bot (PEM/JWT mode)")

# --- Initialize client ---
try:
    client = NijaCoinbaseClient()
    logger.info("✅ CoinbaseClient initialized using PEM/JWT (Advanced=True)")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase client: {e}")
    exit(1)

# --- Fetch USD balance ---
usd_balance = get_usd_balance(client)
logger.info(f"💰 USD Balance: {usd_balance}")

# --- Fetch recent trades (optional) ---
try:
    trades = client.get_recent_trades(limit=5)
    if trades:
        logger.info(f"📈 Recent Trades: {trades}")
    else:
        logger.info("📈 No recent trades found")
except Exception as e:
    logger.warning(f"⚠️ Unable to fetch recent trades: {e}")

logger.info("Bot initialized successfully. Ready for automated trading!")
