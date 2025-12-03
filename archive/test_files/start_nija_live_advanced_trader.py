# start_nija_live_advanced_trader.py
import os
import asyncio
from loguru import logger
from nija_client import CoinbaseClient

# --- Initialize Coinbase Advanced client ---
client = CoinbaseClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET"),
    private_key_path=os.getenv("COINBASE_PRIVATE_KEY_PATH"),
    org_id=os.getenv("COINBASE_ORG_ID"),
    base=os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com"),
    advanced=True
)

# --- Fetch accounts safely ---
def fetch_advanced_accounts():
    try:
        accounts = client.get_accounts()  # v3 endpoint
        if not accounts:
            logger.error("❌ No Advanced accounts found. Check keys and org ID.")
            return []
        logger.info(f"✅ Fetched {len(accounts)} accounts.")
        return accounts
    except Exception as e:
        logger.exception(f"Failed to fetch accounts: {e}")
        return []

# --- Trading logic placeholder ---
async def trading_loop(accounts):
    logger.info("Starting live trading loop...")
    while True:
        try:
            # Example: log balances (replace with your real strategy)
            for acc in accounts:
                balance = float(acc.get("balance", {}).get("amount", 0))
                currency = acc.get("balance", {}).get("currency", "USD")
                logger.info(f"Account {acc.get('id')} balance: {balance} {currency}")
            
            # TODO: Insert your trading logic here (VWAP, RSI, position sizing, etc.)
            
            await asyncio.sleep(5)  # adjust for your trading frequency
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            await asyncio.sleep(5)

# --- Main bot loop ---
async def main_loop():
    logger.info("🚀 Starting Nija Advanced live bot...")
    accounts = fetch_advanced_accounts()
    if not accounts:
        logger.error("No accounts returned. Bot will not start.")
        return
    await trading_loop(accounts)

if __name__ == "__main__":
    asyncio.run(main_loop())
