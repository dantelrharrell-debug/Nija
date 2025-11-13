# nija_app.py
import asyncio
import logging
from nija_client import CoinbaseClient
from nija_trade_logic import main_loop

logger = logging.getLogger("nija.bot.pro")
logging.basicConfig(level=logging.INFO)

def main():
    logger.info("Starting Nija Bot (Live Mode)...")
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Client init failed: %s", str(e))
        raise

    # Test connection
    accounts = client.get_accounts()
    if not accounts:
        logger.error("No accounts returned. Check credentials and permissions.")
        return
    logger.info("✅ Connected! %d accounts detected.", len(accounts))

    # Start live trading loop
    asyncio.run(main_loop())

if __name__ == "__main__":
    main()
