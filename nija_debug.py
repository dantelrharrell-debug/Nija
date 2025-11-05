import logging
from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_debug")

def get_usd_spot_balance():
    try:
        client = CoinbaseClient()
        balance = client.get_usd_spot_balance()
        log.info(f"💰 USD Spot Balance: ${balance:.2f}")
        return balance, client
    except Exception as e:
        log.error(f"❌ Failed to fetch USD Spot balance: {e}")
        return 0.0, None

def get_suggested_trade_size(client, account_balance, risk_factor=1.0):
    try:
        trade_size = client.calculate_position_size(account_balance, risk_factor)
        log.info(f"📊 Suggested Trade Size: ${trade_size:.2f} (Risk Factor: {risk_factor})")
        return trade_size
    except Exception as e:
        log.error(f"❌ Failed to calculate trade size: {e}")
        return 0.0

if __name__ == "__main__":
    balance, client = get_usd_spot_balance()
    if client and balance > 0:
        # Example: Default risk_factor = 1.0 (can adjust higher/lower for confidence)
        suggested_size = get_suggested_trade_size(client, balance, risk_factor=1.0)
