from loguru import logger
from nija_client import CoinbaseClient
from config import LIVE_TRADING

# Initialize client (reuse CoinbaseClient if needed)
client = CoinbaseClient()

def handle_tv_webhook(payload: dict):
    """
    Handles TradingView webhook signals
    Payload example: { "ticker": "BTC/USD", "side": "buy", "size": 0.01 }
    """
    try:
        ticker = payload.get("ticker")
        side = payload.get("side")
        size = float(payload.get("size", 0))

        logger.info(f"TradingView signal received: {side} {size} {ticker}")

        if LIVE_TRADING and ticker and side and size > 0:
            # Map side to Coinbase order type
            order_type = "buy" if side.lower() == "buy" else "sell"
            # Execute trade (example, adjust to your order function)
            result = client.place_order(ticker=ticker, side=order_type, size=size)
            logger.info(f"Order executed: {result}")
        else:
            logger.info("Dry-run mode or incomplete signal. No order placed.")

    except Exception as e:
        logger.exception(f"Failed to handle TradingView webhook: {e}")
