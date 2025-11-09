# nija_app.py
import os
from loguru import logger
from coinbase_advanced_py import CoinbaseAdvancedClient
from decimal import Decimal
from nija_balance_helper import get_usd_balance

# ---------------- Environment variables ----------------
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ISS = os.getenv("COINBASE_ISS")
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

if not COINBASE_PEM_CONTENT or not COINBASE_ISS:
    logger.error("⚠️ Missing Coinbase PEM content or ISS. Set COINBASE_PEM_CONTENT and COINBASE_ISS in env.")
    raise RuntimeError("Missing Coinbase credentials.")

# ---------------- Instantiate Advanced Client ----------------
try:
    client = CoinbaseAdvancedClient(
        pem_content=COINBASE_PEM_CONTENT,
        iss=COINBASE_ISS,
        base_url=COINBASE_API_BASE,
        debug=True  # optional, logs all requests/responses
    )
    logger.info("✅ Coinbase Advanced client initialized successfully.")
except Exception as e:
    logger.exception("❌ Failed to initialize Coinbase Advanced client: %s", e)
    raise

# ---------------- Fetch accounts & USD balance ----------------
try:
    accounts = client.get_accounts()
    if not accounts:
        logger.error("❌ No accounts returned from Coinbase Advanced. Check permissions.")
        raise RuntimeError("No accounts found.")
    logger.info(f"✅ Found {len(accounts)} account(s).")

    usd_balance = get_usd_balance(client)
    logger.info(f"💰 USD Balance: {usd_balance}")
except Exception as e:
    logger.exception("❌ Failed to fetch accounts or balances: %s", e)
    raise

# ---------------- Fetch recent trades (optional) ----------------
try:
    recent_trades = client.get_recent_trades(limit=5)
    logger.info(f"📈 Recent trades (last 5): {recent_trades}")
except Exception:
    logger.warning("⚠️ Could not fetch recent trades. Ignoring.")

# ---------------- Ready for trading ----------------
logger.info("🚀 Nija bot is ready for trading!")
