import logging
from nija_client import get_usd_spot_balance, get_all_accounts, calculate_position_size

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_debug")

try:
    usd_balance = get_usd_spot_balance()
    log.info(f"✅ USD Spot Balance: ${usd_balance:.2f}")

    accounts = get_all_accounts()
    log.info(f"✅ Fetched {len(accounts)} accounts")

    # Example: calculate trade size
    trade_size = calculate_position_size(usd_balance, risk_factor=5)
    log.info(f"✅ Suggested Trade Size: ${trade_size:.2f}")

except Exception as e:
    log.error(f"❌ Error in Nija debug: {e}")
