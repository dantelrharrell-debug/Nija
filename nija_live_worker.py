# nija_live_worker.py
import time
import logging
from nija_coinbase_client import CoinbaseClient, get_usd_balance
from trading_logic import decide_trade  # your main trade decision logic
from nija_coinbase_jwt import get_jwt_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

logger.info("[NIJA] Starting Nija Trading Bot...")

# --- Initialize client ---
try:
    client = CoinbaseClient(jwt_token=get_jwt_token())
    logger.info("[NIJA] Coinbase client initialized successfully.")
except Exception as e:
    logger.error("[NIJA] Failed to initialize Coinbase client: %s", e)
    raise

# --- Worker loop ---
MIN_PCT = 0.02
MAX_PCT = 0.1
MIN_USD = 1.0

while True:
    try:
        usd_balance = get_usd_balance(client)
        if usd_balance < MIN_USD:
            logger.warning("[NIJA] USD balance too low (%s). Waiting...", usd_balance)
            time.sleep(30)
            continue

        # Decide trade based on your strategy
        trade_signal = decide_trade(client)
        if trade_signal:
            logger.info("[NIJA] Trade decision: %s", trade_signal)
            # Execute trade (CoinbaseClient handles live orders)
            client.execute_trade(trade_signal)
        else:
            logger.info("[NIJA] No trade signal detected.")

        time.sleep(5)  # small pause between checks

    except KeyboardInterrupt:
        logger.info("[NIJA] Stopping worker gracefully.")
        break
    except Exception as e:
        logger.error("[NIJA] Worker error: %s", e)
        time.sleep(10)
