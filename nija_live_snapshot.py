#!/usr/bin/env python3
import os
import base64
import logging
from pathlib import Path

# -------------------------------
# ENVIRONMENT VARIABLES
# -------------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_PEM_B64 = os.getenv("API_PEM_B64")

# -------------------------------
# LOGGING
# -------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("NijaBot")

logger.debug(f"COINBASE_API_KEY={COINBASE_API_KEY}")
logger.debug(f"COINBASE_API_SECRET={COINBASE_API_SECRET}")
logger.debug(f"COINBASE_API_PASSPHRASE={COINBASE_API_PASSPHRASE}")
logger.debug(f"API_PEM_B64={'<hidden>' if API_PEM_B64 else 'NOT SET'}")

# -------------------------------
# COINBASE CLIENT SETUP
# -------------------------------
try:
    from coinbase_advanced_py.client import CoinbaseClient
    coinbase_client = CoinbaseClient(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET,
        passphrase=COINBASE_API_PASSPHRASE,
    )
    logger.info("Coinbase client initialized. Live trading enabled.")
except ImportError:
    logger.warning("⚠️ coinbase_advanced_py.client not found. Real trading disabled.")
    coinbase_client = None

# -------------------------------
# FUNCTION TO DECODE PEM
# -------------------------------
def decode_pem_b64(api_pem_b64: str) -> bytes:
    if not api_pem_b64:
        raise ValueError("API_PEM_B64 is empty or not set in environment.")
    
    # Remove non-base64 chars (spaces, newlines)
    sanitized = ''.join(c for c in api_pem_b64 if c.isalnum() or c in '+/=')
    
    # Fix padding
    missing_padding = len(sanitized) % 4
    if missing_padding:
        sanitized += '=' * (4 - missing_padding)
    
    return base64.b64decode(sanitized)

# -------------------------------
# WRITE PEM FILE
# -------------------------------
pem_path = Path("/tmp/nija_api.pem")  # You can adjust the path
try:
    with open(pem_path, "wb") as f:
        f.write(decode_pem_b64(API_PEM_B64))
    logger.info(f"API PEM file written successfully to {pem_path}")
except Exception as e:
    logger.error(f"Failed to write API PEM file: {e}")
    raise

# -------------------------------
# START BOT
# -------------------------------
def start_bot():
    if not coinbase_client:
        logger.warning("Coinbase client not initialized. Bot running in simulation mode.")
    else:
        logger.info("Starting live trading loop...")
    
    # Add your trading loop or snapshot logic here
    # Example placeholder:
    while True:
        logger.debug("Bot heartbeat...")
        import time
        time.sleep(10)

if __name__ == "__main__":
    start_bot()
