import os

# ================================
# Coinbase Advanced API Config
# ================================

# Organization ID
COINBASE_ORG_ID = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"

# JWT Authentication
COINBASE_JWT_KID = "9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
COINBASE_JWT_ISSUER = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
COINBASE_JWT_PEM = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----
"""

# Optional fallback API key (if needed)
COINBASE_API_KEY = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
COINBASE_API_SECRET = "YOUR_API_SECRET_IF_NEEDED"
COINBASE_API_PASSPHRASE = ""

# Base URL
COINBASE_API_BASE = "https://api.coinbase.com"

# ================================
# Trading Settings
# ================================

# Live trading flag
LIVE_TRADING = True

# Default trading account
TRADING_ACCOUNT_ID = "14f3af21-7544-412c-8409-98dc92cd2eec"

# Auto-scaling threshold (balance-based)
AUTO_SCALE_LOW = 50  # e.g., apply scaling if balance < $50

# Spot & Futures tickers
SPOT_TICKERS = ["BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD"]
FUTURES_TICKERS = ["BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD"]

# ================================
# Logging
# ================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
