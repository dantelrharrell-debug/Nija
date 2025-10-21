# nija_bot_web/config.py

# Spot & Futures tickers
SPOT_TICKERS = ["BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD"]
FUTURES_TICKERS = ["BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD"]

# Auto-scaling threshold
AUTO_SCALE_LOW = 50  # Apply special scaling if balance < $50
