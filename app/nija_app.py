# nija_app.py
import os
import sys
from loguru import logger
from decimal import Decimal
from coinbase_advanced_py import CoinbaseAdvancedClient

# ----------------------------
# Environment / Config
# ----------------------------
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ISS = os.getenv("COINBASE_ISS")
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

if not PEM_CONTENT or not COINBASE_ISS:
    logger.error("Missing Coinbase Advanced credentials (COINBASE_PEM_CONTENT or COINBASE_ISS)")
    sys.exit(1)

# ----------------------------
# Initialize client
# ----------------------------
try:
    client = CoinbaseAdvancedClient(
        pem_content=PEM_CONTENT,
        iss=COINBASE_ISS,
        base_url=COINBASE_API_BASE,
        debug=True  # set to False in production
    )
    logger.info("✅ Coinbase Advanced client initialized successfully.")
except Exception as e:
    logger.exception(f"Failed to initialize Coinbase Advanced client: {e}")
    sys.exit(1)

# ----------------------------
# Helper: fetch USD balance
# ----------------------------
def get_usd_balance(client) -> Decimal:
    try:
        balances = client.get_spot_account_balances()
        usd = balances.get("USD") or balances.get("USDC") or 0
        return Decimal(str(usd))
    except Exception as e:
        logger.exception(f"Failed to fetch USD balance: {e}")
        return Decimal("0")

# ----------------------------
# Main diagnostics / test
# ----------------------------
if __name__ == "__main__":
    usd_balance = get_usd_balance(client)
    logger.info(f"USD Balance: {usd_balance}")

    try:
        trades = client.get_recent_trades(limit=5)
        logger.info(f"Recent Trades: {trades}")
    except Exception as e:
        logger.warning(f"Failed to fetch recent trades: {e}")
