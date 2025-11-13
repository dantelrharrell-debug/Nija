# nija_app.py
import os
import sys
import time
from loguru import logger
from nija_client import CoinbaseClient

# Ensure unbuffered output for Railway logs
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

logger.info("🚀 Nija Bot container started...")

# Validate environment variables
required_envs = ["COINBASE_API_KEY_ID", "COINBASE_PEM", "COINBASE_ORG_ID"]
missing = [e for e in required_envs if not os.environ.get(e)]
if missing:
    logger.error("❌ Missing environment variables: {}", missing)
    sys.exit(1)

def main():
    try:
        logger.info("Initializing Coinbase client...")
        client = CoinbaseClient()
        logger.info("✅ Coinbase client initialized with org ID: {}", client.org_id)
    except Exception as e:
        logger.exception("❌ Failed to initialize Coinbase client: {}", e)
        sys.exit(1)

    # Test accounts
    try:
        accounts = client.get_accounts()
        if not accounts or not accounts.get("data"):
            logger.error("❌ /accounts returned no data! Check API key permissions.")
            sys.exit(1)

        data = accounts.get("data")
        logger.info("✅ Connected to Coinbase! Retrieved {} accounts.", len(data))
        # Print small summary
        for a in data[:5]:
            bal = a.get("balance", {})
            logger.info(" - {}: {} {}", a.get("name") or a.get("currency"), bal.get("amount"), bal.get("currency"))

    except Exception as e:
        logger.exception("❌ Failed to fetch accounts: {}", e)
        sys.exit(1)

    # Placeholder: Bot main loop goes here
    logger.info("✅ Bot ready to accept TradingView alerts (live trading disabled in this starter template).")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("❌ Fatal error on startup: {}", e)
        sys.exit(1)
