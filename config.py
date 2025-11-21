import os

# ===========================
# Trading Mode Configuration
# ===========================
# MODE can be: SANDBOX, DRY_RUN, or LIVE (default: DRY_RUN)
MODE = os.getenv("MODE", "DRY_RUN").upper()

# Safety checks for LIVE mode
COINBASE_ACCOUNT_ID = os.getenv("COINBASE_ACCOUNT_ID", "")
CONFIRM_LIVE = os.getenv("CONFIRM_LIVE", "false").lower() == "true"

# ===========================
# Coinbase API Configuration
# ===========================
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

# Coinbase Org + JWT
COINBASE_ORG_ID = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
COINBASE_JWT_KID = "9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
COINBASE_JWT_ISSUER = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
COINBASE_JWT_PEM = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----"""

# Optional API key fallback
COINBASE_API_KEY = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
COINBASE_API_SECRET = ""

LIVE_TRADING = True
TRADING_ACCOUNT_ID = "14f3af21-7544-412c-8409-98dc92cd2eec"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ===========================
# Trading Safety Limits
# ===========================
MAX_ORDER_USD = float(os.getenv("MAX_ORDER_USD", "100"))
MAX_ORDERS_PER_MINUTE = int(os.getenv("MAX_ORDERS_PER_MINUTE", "5"))
MANUAL_APPROVAL_COUNT = int(os.getenv("MANUAL_APPROVAL_COUNT", "0"))

# ===========================
# Audit Logging
# ===========================
LOG_PATH = os.getenv("LOG_PATH", "orders.log")

# Tickers
SPOT_TICKERS = ["BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD"]
FUTURES_TICKERS = SPOT_TICKERS.copy()

# ===========================
# TradingView Webhook Configuration
# ===========================
TRADINGVIEW_WEBHOOK_SECRET = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "your_webhook_secret_here")
TV_WEBHOOK_SECRET = TRADINGVIEW_WEBHOOK_SECRET  # Keep backward compatibility
TV_WEBHOOK_PORT = int(os.getenv("TV_WEBHOOK_PORT", "5000"))

# ===========================
# Trading Percentages
# ===========================
MIN_TRADE_PERCENT = float(os.getenv("MIN_TRADE_PERCENT", "1.0"))
MAX_TRADE_PERCENT = float(os.getenv("MAX_TRADE_PERCENT", "5.0"))
