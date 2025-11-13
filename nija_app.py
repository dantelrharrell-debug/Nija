# nija_app.py
import os
import sys
import asyncio
from loguru import logger
from nija_client import CoinbaseClient

# Ensure logs flush immediately (Railway-friendly)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# --- Trading config placeholders ---
MIN_POSITION = 0.02
MAX_POSITION = 0.10
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]

async def keep_alive():
    """Keeps container alive while trading logic runs."""
    while True:
        await asyncio.sleep(60)

async def live_trading_loop(client):
    """Placeholder for live trading loop."""
    while True:
        try:
            accounts = client.get_accounts()
            data = accounts.get("data") if isinstance(accounts, dict) else None
            if not data:
                logger.warning("❌ No accounts fetched. Check API key permissions.")
            else:
                logger.info("✅ Connected! Accounts fetched: %d", len(data))
                # Print first few account summaries
                for a in data[:5]:
                    bal = a.get("balance", {})
                    logger.info(" - %s: %s %s", a.get("name") or a.get("currency"),
                                bal.get("amount"), bal.get("currency"))
            # Placeholder: add your trading logic here
        except Exception as e:
            logger.error("Live loop error: %s", e)

        # Sleep before next iteration (adjust for real-time trading frequency)
        await asyncio.sleep(15)

async def main():
    logger.info("Starting Nija Bot (Railway-ready)...")

    # Initialize Coinbase client
    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error("Cannot initialize Coinbase client: %s", e)
        return

    # Run live trading loop and keep-alive concurrently
    await asyncio.gather(
        live_trading_loop(client),
        keep_alive()
    )

if __name__ == "__main__":
    asyncio.run(main())
