# app/start_bot_main.py
import os
import time
import threading
from loguru import logger

# Import your local JWT-based client (we implemented this earlier)
from app.nija_client import CoinbaseClient

logger.info("start_bot_main.py loaded")

def trading_loop(client):
    """Very small safe background loop: fetch accounts & log every 30s.
    Replace or expand with your live trading logic once connection is confirmed."""
    try:
        while True:
            try:
                resp = client.get_accounts()
                accounts = resp.get("data") if isinstance(resp, dict) else []
                logger.info("Trading loop: fetched %d accounts", len(accounts))
                # TODO: call your trading logic for each account here
            except Exception as e:
                logger.exception("Trading loop: error fetching accounts: {}", e)
            time.sleep(30)
    except Exception as e:
        logger.exception("Trading loop fatal error: {}", e)

def start_bot_main():
    """Initialize Coinbase client and launch background trading loop (non-blocking)."""
    logger.info("Starting bot initialization...")

    try:
        # Instantiate local CoinbaseClient which reads env vars:
        # COINBASE_API_KEY_ID, COINBASE_PEM, COINBASE_ORG_ID
        client = CoinbaseClient()
        logger.info("CoinbaseClient initialized with org ID: %s", client.org_id)
    except Exception as e:
        logger.exception("Failed to initialize CoinbaseClient: {}", e)
        # re-raise or return depending on how you want main.py to behave
        return

    # Test accounts endpoint once and log a friendly message
    try:
        accounts_resp = client.get_accounts()
        accounts = accounts_resp.get("data") if isinstance(accounts_resp, dict) else []
        if not accounts:
            logger.error("Connection test failed: /accounts returned no data. Check API key permissions and org ID.")
            # Do not start trading loop if no accounts
            return
        logger.info("✅ Connected to Coinbase! Retrieved %d accounts.", len(accounts))
        for a in accounts[:5]:
            bal = a.get("balance", {})
            logger.info(" - %s: %s %s", a.get("name") or a.get("currency"), bal.get("amount"), bal.get("currency"))
    except Exception as e:
        logger.exception("Failed to fetch accounts during startup: {}", e)
        return

    # Start the background trading loop so main.py can continue printing heartbeats
    t = threading.Thread(target=trading_loop, args=(client,), daemon=True)
    t.start()
    logger.info("Background trading loop started (daemon thread).")
