import time
import logging
from nija_client import CoinbaseClient  # Must be the working client above

# --- Initialize Coinbase client ---
coinbase_client = CoinbaseClient(
    api_key="YOUR_API_KEY",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",  # usually empty for Advanced API
    api_sub="YOUR_ACCOUNT_SUB_ID",  # must match your funded account
)

# --- Trading configuration ---
LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds between checks

# --- Trading signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]
