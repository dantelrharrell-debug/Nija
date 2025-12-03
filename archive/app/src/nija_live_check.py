# nija_live_check.py
import logging
from decimal import Decimal
from nija_client import client, get_usd_balance, CLIENT_CLASS
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_live_check")

logger.info("🚀 Starting Nija live readiness check...")

# --- 1️⃣ Check client ---
if client is None:
    logger.error("Client not initialized. Abort.")
    sys.exit(1)

logger.info("Client class detected: %s", type(client).__name__)

# --- 2️⃣ Check USD balance ---
balance = get_usd_balance(client)
logger.info("USD Balance: %s", balance)

if not isinstance(balance, Decimal):
    logger.error("Balance is not Decimal: %r", balance)
    sys.exit(1)

if balance <= 0:
    logger.warning("USD balance is zero. Deposit funds to trade live.")

# --- 3️⃣ Check LIVE_TRADING environment ---
live_mode = os.getenv("LIVE_TRADING", "0") == "1"
if live_mode:
    logger.info("LIVE_TRADING=1 → Bot will trade real funds.")
else:
    logger.warning("LIVE_TRADING is not enabled. Bot will simulate trades only.")

# --- 4️⃣ Test trade simulation (dry-run) ---
test_amount = 0.0001  # tiny amount for simulation
product_id = "BTC-USD"

try:
    if hasattr(client, "place_order") and live_mode:
        logger.info("Attempting test order...")
        order = client.place_order(product_id=product_id, side="buy", size=test_amount)
        logger.info("Test order placed: %s", order)
    else:
        logger.info("Simulating order (dry-run) for %s BTC", test_amount)
        logger.info("[DRY-RUN] Buy %s %s simulated successfully", test_amount, product_id)
except Exception as e:
    logger.error("Trade simulation failed: %s", e)
    sys.exit(1)

logger.info("✅ Nija live check completed. Bot ready to run!")
