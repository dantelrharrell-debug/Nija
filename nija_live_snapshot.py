#!/usr/bin/env python3
import os
import sys
import base64
import logging
from pathlib import Path

# ---------------------------
# Setup logging
# ---------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s:%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ---------------------------
# Load environment variables
# ---------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_PEM_B64 = os.getenv("API_PEM_B64")

logging.debug(f"COINBASE_API_KEY={COINBASE_API_KEY}")
logging.debug(f"COINBASE_API_SECRET={COINBASE_API_SECRET}")
logging.debug(f"COINBASE_API_PASSPHRASE={COINBASE_API_PASSPHRASE}")
logging.debug(f"API_PEM_B64 length={len(API_PEM_B64) if API_PEM_B64 else 0}")

# ---------------------------
# Fix Base64 padding
# ---------------------------
def fix_base64_padding(s: str) -> str:
    s = s.strip().replace("\n", "")
    return s + '=' * (-len(s) % 4)

# ---------------------------
# Write PEM file safely
# ---------------------------
pem_path = Path("coinbase_api.pem")
if API_PEM_B64:
    try:
        with open(pem_path, "wb") as f:
            f.write(base64.b64decode(fix_base64_padding(API_PEM_B64)))
        logging.info(f"✅ PEM file written to {pem_path}")
    except Exception as e:
        logging.error(f"❌ Failed to write PEM file: {e}")
else:
    logging.warning("⚠️ API_PEM_B64 is empty. PEM file not created.")

# ---------------------------
# Add vendor path for Coinbase client
# ---------------------------
sys.path.insert(0, os.path.join(os.getcwd(), "vendor"))

try:
    from coinbase_advanced_py.client import CoinbaseClient
    logging.info("✅ CoinbaseClient imported successfully.")
except ImportError:
    logging.warning("⚠️ coinbase_advanced_py.client not found. Real trading disabled.")
    CoinbaseClient = None

# ---------------------------
# Initialize Coinbase client if possible
# ---------------------------
client = None
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_PASSPHRASE,
            pem_path=str(pem_path)
        )
        logging.info("✅ Coinbase client initialized. Ready for live trading.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize Coinbase client: {e}")

# ---------------------------
# Start bot (placeholder)
# ---------------------------
logging.info("🌟 Starting Nija bot main loop...")

# Example: you can replace this with your actual trading loop
try:
    while True:
        # Example heartbeat
        logging.debug("Bot heartbeat...")
        import time
        time.sleep(5)
except KeyboardInterrupt:
    logging.info("🛑 Nija bot stopped by user.")
