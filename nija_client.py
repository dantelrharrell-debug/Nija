# nija_client.py
#!/usr/bin/env python3

import os
import logging
import threading
import time

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# -----------------------------
# Try to initialize real Coinbase REST client
# -----------------------------
try:
    from coinbase.rest import RESTClient

    client = RESTClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET")
    )
    logging.info("✅ Real Coinbase client initialized.")
    REAL_CLIENT = True
except Exception as e:
    logging.warning(f"❌ Failed to init real Coinbase client: {e}")
    REAL_CLIENT = False

    # Fallback stub client
    class StubClient:
        def get_accounts(self):
            return [
                {"currency": "USD", "balance": {"amount": "1000.00"}},
                {"currency": "BTC", "balance": {"amount": "0.0000"}},
            ]

        def place_order(self, **kwargs):
            logging.info(f"💤 Stub order simulated: {kwargs}")

    client = StubClient()
    logging.info("⚠️ Using stub Coinbase client.")

# -----------------------------
# Helper functions
# -----------------------------
def get_accounts():
    try:
        accounts = client.get_accounts()
        logging.info("💰 Accounts:")
        for a in accounts:
            if REAL_CLIENT:
                # RESTClient returns nested JSON objects differently
                currency = a.get("currency") or a.get("currency_code")
                balance = a.get("balance", {}).get("amount")
            else:
                currency = a["currency"]
                balance = a["balance"]["amount"]
            logging.info(f" - {currency}: {balance}")
        return accounts
    except Exception as e:
        logging.error(f"Failed to fetch accounts: {e}")
        return []

def place_order(order_type="buy", product_id="BTC-USD", size=0.001, price=None):
    try:
        if REAL_CLIENT:
            order = client.place_order(
                product_id=product_id,
                side=order_type,
                type="limit" if price else "market",
                size=size,
                price=price
            )
            logging.info(f"✅ Order placed: {order}")
        else:
            client.place_order(
                order_type=order_type,
                product_id=product_id,
                size=size,
                price=price
            )
    except Exception as e:
        logging.error(f"Failed to place order: {e}")

# -----------------------------
# Trading loop
# -----------------------------
_trading_thread = None
_trading_active = False

def _trading_loop():
    logging.info(f"🔥 Trading loop starting (pid={threading.get_ident()}) 🔥")
    while _trading_active:
        # Example strategy: check accounts, place a dummy order
        accounts = get_accounts()
        # Place small market buy if USD balance > 10
        usd_balance = next((float(a["balance"]["amount"]) for a in accounts if a["currency"] == "USD"), 0)
        if usd_balance >= 10:
            place_order(order_type="buy", size=0.001)
        time.sleep(10)  # wait 10s between iterations

def start_trading():
    global _trading_thread, _trading_active
    if _trading_thread and _trading_thread.is_alive():
        logging.info("⚠️ Trading loop already running.")
        return
    _trading_active = True
    _trading_thread = threading.Thread(target=_trading_loop, daemon=True)
    _trading_thread.start()
    logging.info("🔥 Trading loop thread started")

def stop_trading():
    global _trading_active
    _trading_active = False
    logging.info("🛑 Trading loop stopped")
