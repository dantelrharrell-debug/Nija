#!/usr/bin/env python3
import os
import time
import threading
from coinbase_advanced_py.client import CoinbaseClient

# -------------------------------
# Coinbase API credentials
# -------------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

# -------------------------------
# Initialize Coinbase Client
# -------------------------------
if not all([API_KEY, API_SECRET]):
    print("⚠️ Coinbase keys missing, using stub client")
    from coinbase_advanced_py.stub_client import StubClient as CoinbaseClient

client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)

# -------------------------------
# Trading Loop
# -------------------------------
running = False

def trading_loop():
    global running
    running = True
    print("🔥 Trading loop started 🔥")
    try:
        while running:
            # Add your live trading logic here
            time.sleep(5)  # placeholder
    except Exception as e:
        print(f"Trading loop error: {e}")
    finally:
        print("Trading loop exited cleanly")

def start_trading():
    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()
    return thread
