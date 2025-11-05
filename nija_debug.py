import logging
import os
from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_debug")

def get_usd_spot_balance():
    """Fetch USD spot balance from Coinbase account."""
    try:
        client = CoinbaseClient()
        balance = client.get_usd_spot_balance()
        log.info(f"💰 USD Spot Balance: ${balance:.2f}")
        return balance, client
    except Exception as e:
        log.error(f"❌ Failed to fetch USD Spot balance: {e}")
        return 0.0, None

def get_suggested_trade_size(client, account_balance, risk_factor=1.0):
    """Calculate suggested trade size based on account balance and risk factor."""
    try:
        trade_size = client.calculate_position_size(account_balance, risk_factor)
        log.info(f"📊 Suggested Trade Size: ${trade_size:.2f} (Risk Factor: {risk_factor})")
        return trade_size
    except Exception as e:
        log.error(f"❌ Failed to calculate trade size: {e}")
        return 0.0

def get_risk_factor_from_alert():
    """
    Example: Get risk factor from TradingView alert.
    TRADINGVIEW_RISK environment variable should be set via alert payload.
    """
    try:
        risk = float(os.getenv("TRADINGVIEW_RISK", 1.0))
        risk = max(0.5, min(risk, 10.0))  # clamp between 0.5 and 10
        log.info(f"⚡ Risk factor from alert: {risk}")
        return risk
    except Exception as e:
        log.warning(f"⚠️ Invalid risk factor from alert, defaulting to 1.0: {e}")
        return 1.0

if __name__ == "__main__":
    # 1️⃣ Get USD balance
    balance, client = get_usd_spot_balance()
    if client and balance > 0:
        # 2️⃣ Get risk factor from alert
        risk_factor = get_risk_factor_from_alert()
        # 3️⃣ Calculate trade size
        suggested_size = get_suggested_trade_size(client, balance, risk_factor=risk_factor)
