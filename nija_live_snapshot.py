import os
import base64
import logging
from nija_client import start_trading
from coinbase_advanced_py.client import CoinbaseClient

logging.basicConfig(level=logging.INFO)

# Read environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_PEM_B64 = os.getenv("API_PEM_B64")

# Fix padding for base64
if API_PEM_B64:
    API_PEM_B64 += "=" * (-len(API_PEM_B64) % 4)

pem_path = "coinbase_api.pem"
if API_PEM_B64:
    try:
        with open(pem_path, "wb") as f:
            f.write(base64.b64decode(API_PEM_B64))
        logging.info("✅ PEM file written successfully")
    except Exception as e:
        logging.error(f"❌ Failed to decode PEM: {e}")
        pem_path = None

# Initialize Coinbase client
client = None
if CoinbaseClient and API_KEY and API_SECRET and API_PASSPHRASE and pem_path:
    try:
        client = CoinbaseClient(
            key=API_KEY,
            secret=API_SECRET,
            passphrase=API_PASSPHRASE,
            pem_file=pem_path
        )
        logging.info("✅ Coinbase client initialized")
    except Exception as e:
        logging.error(f"❌ Failed to init Coinbase client: {e}")

# Start trading loop
start_trading(client)#!/usr/bin/env python3
import os
import sys
import base64
from nija_client import client  # make sure vendor folder is on sys.path

# Ensure vendor folder is loaded
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

# Load environment variables
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
API_PEM_B64 = os.environ.get("API_PEM_B64")

# Fix base64 padding if missing
def fix_base64_padding(b64_string):
    b64_string = b64_string.replace("\n", "").replace(" ", "")
    missing_padding = len(b64_string) % 4
    if missing_padding:
        b64_string += "=" * (4 - missing_padding)
    return b64_string

# Decode PEM
if API_PEM_B64:
    pem_path = "coinbase_api.pem"
    try:
        with open(pem_path, "wb") as f:
            f.write(base64.b64decode(fix_base64_padding(API_PEM_B64)))
        print(f"✅ PEM file written to {pem_path}")
    except Exception as e:
        print(f"❌ Error decoding PEM: {e}")
        sys.exit(1)
else:
    print("❌ API_PEM_B64 not set")
    sys.exit(1)

# Initialize Coinbase client
try:
    from coinbase_advanced_py.client import CoinbaseClient
    coinbase_client = CoinbaseClient(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET,
        api_passphrase=COINBASE_API_PASSPHRASE,
        api_pem_path=pem_path
    )
    print("✅ Coinbase client initialized. Live trading enabled.")
except Exception as e:
    print(f"⚠️ Coinbase client error: {e}. Real trading disabled.")

# Start Nija bot loop
from nija_client import start_trading
start_trading(coinbase_client)
