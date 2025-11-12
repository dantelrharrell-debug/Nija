# nija_app.py
from nija_client import CoinbaseClient
from loguru import logger
import os

MIN_POSITION = 0.02
MAX_POSITION = 0.10

def main():
    logger.info("Starting Nija loader (robust)...")
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Client init failed: %s", e)
        raise

    # Determine auth mode for logs
    use_jwt = bool(client.pem_content)
    logger.info("Auth mode: %s", "JWT" if use_jwt else "API-KEY")

    # Test accounts
    try:
        accounts = client.get_accounts()
        data = accounts.get("data") if isinstance(accounts, dict) else None
        if not data:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            return
        logger.info("✅ Connected to Coinbase! Retrieved %d accounts.", len(data))
        # print small summary
        for a in data[:5]:
            bal = a.get("balance", {})
            logger.info(" - %s: %s %s", a.get("name") or a.get("currency"), bal.get("amount"), bal.get("currency"))
    except Exception as e:
        logger.error("Connection test failed: %s", e)
        return

    # Bot ready; placeholder loop removed for safety
    logger.info("Bot initialized and ready to accept TradingView alerts (not running trades in this starter template).")

if __name__ == "__main__":
    main()
