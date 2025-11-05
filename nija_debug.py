# nija_debug.py
import logging
from nija_client import CoinbaseClient, calculate_position_size

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_debug")

def main():
    log.info("✅ Starting Nija preflight check...")

    # Masked env debug info (optional)
    import os
    log.info(f"ℹ️ COINBASE_API_KEY: {'%s'}")
    log.info(f"ℹ️ COINBASE_API_PASSPHRASE: {'%s'}")

    # Initialize Coinbase client
    try:
        client = CoinbaseClient()  # No preflight argument needed
        log.info("✅ CoinbaseClient initialized successfully.")
    except Exception as e:
        log.error(f"❌ Error creating CoinbaseClient: {e}")
        return

    # Fetch USD balance
    try:
        usd_balance = client.get_usd_spot_balance()
        log.info(f"💰 USD Balance: ${usd_balance:.2f}")
    except Exception as e:
        log.error(f"❌ Failed to fetch USD Spot balance: {e}")
        usd_balance = 0

    # Calculate position size
    try:
        trade_size = calculate_position_size(usd_balance)
        log.info(f"📊 Suggested trade size: ${trade_size:.2f}")
    except Exception as e:
        log.warning(f"⚠️ Cannot calculate position size: {e}")

    # Fetch all accounts for debugging
    try:
        accounts = client.get_all_accounts()
        log.info(f"📂 Accounts fetched: {len(accounts)}")
    except Exception as e:
        log.error(f"❌ Failed to fetch all accounts: {e}")

if __name__ == "__main__":
    main()
