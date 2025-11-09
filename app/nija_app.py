# nija_app.py
import os
import sys
import time
from loguru import logger

# --- Logger ---
logger = logger.bind(name="nija_startup")

# --- Import Coinbase Advanced client ---
try:
    from coinbase_advanced_py.client import Client as CoinbaseAdvancedClient
    logger.info("Coinbase Advanced client imported successfully")
except ImportError as e:
    logger.error(f"Cannot import Coinbase Advanced client: {e}")
    sys.exit(1)

# --- Read PEM / JWT from environment ---
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")   # Must have real newlines
COINBASE_ISS = os.getenv("COINBASE_ISS")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

if not PEM_CONTENT or not COINBASE_ISS:
    logger.error("Missing COINBASE_PEM_CONTENT or COINBASE_ISS in environment")
    sys.exit(1)

# --- Initialize Advanced Client ---
try:
    client = CoinbaseAdvancedClient(
        issuer=COINBASE_ISS,
        pem_content=PEM_CONTENT,
        base_url=BASE_URL
    )
    logger.success("Coinbase Advanced client initialized successfully")
except Exception as e:
    logger.exception(f"Failed to initialize Coinbase Advanced client: {e}")
    sys.exit(1)

# --- Verify connection by fetching accounts ---
def list_accounts():
    try:
        accounts_resp = client.get_accounts()
        # Some clients return .json(), some return list/dict
        if hasattr(accounts_resp, "json"):
            data = accounts_resp.json()
        else:
            data = accounts_resp

        accounts = data.get("accounts", data)
        for acc in accounts:
            balance = acc.get("balance", {})
            amt = balance.get("amount") if isinstance(balance, dict) else balance
            currency = balance.get("currency") if isinstance(balance, dict) else None
            logger.info(f"Account: {acc.get('name')} | Balance: {amt} {currency}")
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return []

# --- Live trading loop placeholder ---
def live_trading_loop():
    logger.info("Starting live trading loop...")
    while True:
        try:
            # Example placeholder: log USD balance every 5 sec
            accounts = list_accounts()
            usd_balance = 0
            for a in accounts:
                bal = a.get("balance", {})
                if (a.get("currency") == "USD") or (bal.get("currency") == "USD"):
                    usd_balance += float(bal.get("amount", 0))
            logger.info(f"USD balance: {usd_balance}")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

# --- Entry point ---
if __name__ == "__main__":
    list_accounts()       # Show accounts at startup
    live_trading_loop()   # Start trading loop
