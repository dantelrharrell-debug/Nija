# app/start_bot_main.py
import os
from loguru import logger
from nija_client import CoinbaseClient

# --- Load env variables ---
from dotenv import load_dotenv

env_file = ".env"
if os.path.exists(env_file):
    load_dotenv(env_file)
    logger.info(".env loaded successfully")
else:
    logger.warning(".env file not found, using system env vars")

# --- Verify required env vars ---
required_vars = ["COINBASE_API_KEY_ID", "COINBASE_PEM", "COINBASE_ORG_ID"]
missing = [v for v in required_vars if not os.getenv(v)]
if missing:
    logger.error("Missing required env vars: %s", ", ".join(missing))
    raise RuntimeError("Cannot start bot without Coinbase credentials")

# --- Initialize Coinbase client ---
try:
    client = CoinbaseClient()
    logger.info("Coinbase client initialized successfully.")
except Exception as e:
    logger.error("Cannot initialize Coinbase client: %s", e)
    raise

# --- Test accounts ---
try:
    accounts_resp = client.get_accounts()
    accounts = accounts_resp.get("data") if isinstance(accounts_resp, dict) else None
    if not accounts:
        logger.error("❌ Connection test failed! /accounts returned no data.")
        raise RuntimeError("Cannot continue without account info")

    logger.info("✅ Connected to Coinbase! Retrieved %d accounts.", len(accounts))
    for a in accounts[:5]:
        bal = a.get("balance", {})
        logger.info(" - %s: %s %s", a.get("name") or a.get("currency"), bal.get("amount"), bal.get("currency"))

except Exception as e:
    logger.error("Failed to fetch accounts: %s", e)
    raise RuntimeError("Cannot continue without account info")

logger.info("Bot initialized and ready to accept TradingView alerts or start trading.")
