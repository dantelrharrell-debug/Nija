# start_bot.py
import os
import time
from loguru import logger

try:
    from nija_client import CoinbaseClient as _Client
except ImportError:
    try:
        from nija_client import NijaCoinbaseClient as _Client
    except ImportError:
        raise ImportError("Neither 'CoinbaseClient' nor 'NijaCoinbaseClient' could be imported from nija_client.py")

# --- Initialize client ---
client = _Client()

logger.info("Starting Nija bot (entrypoint)")

# --- Fetch USD balance safely ---
try:
    if hasattr(client, "get_balances"):
        balances = client.get_balances()
    elif hasattr(client, "get_accounts"):
        balances = client.get_accounts()
    else:
        balances = {}
    usd_balance = balances.get("USD", 0) if isinstance(balances, dict) else 0
    logger.success(f"USD balance fetched: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
    usd_balance = 0

# --- Startup complete message ---
logger.info("Startup complete — bot ready for live trading")

# --- Example live loop (replace with your trading logic) ---
try:
    while True:
        # Fetch balances each tick
        try:
            balances = client.get_balances()
            usd_balance = balances.get("USD", 0) if isinstance(balances, dict) else 0
            logger.info(f"[NIJA-BALANCE] USD: {usd_balance}")
        except Exception as e:
            logger.warning(f"Balance fetch failed: {e}")
        
        # --- TODO: insert live trading signal handling here ---
        # e.g., listen for TradingView alerts, execute trade

        time.sleep(5)  # tick interval; adjust as needed
except KeyboardInterrupt:
    logger.info("Bot stopped manually")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
finally:
    logger.info("Exiting Nija bot")
