import os
import logging
import time
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# --- Load Coinbase environment variables ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # Single-line escaped PEM
LIVE_TRADING = os.getenv("LIVE_TRADING", "False").lower() in ["1", "true", "yes"]
TRADING_ACCOUNT_ID = os.getenv("TRADING_ACCOUNT_ID")  # Optional: explicitly set

if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT]):
    logging.error("❌ Missing Coinbase envs: COINBASE_ORG_ID, COINBASE_API_KEY_ID, or COINBASE_PEM_CONTENT")
    exit(1)

# --- Normalize PEM and load key ---
try:
    pem_bytes = COINBASE_PEM_CONTENT.encode('utf-8')
    private_key = serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())
    logging.info("✅ PEM loaded successfully and valid EC key.")
except Exception as e:
    logging.error(f"❌ Failed to load PEM. Check formatting and copy/paste: {e}")
    exit(1)

# --- Show IP for Coinbase Advanced whitelist ---
try:
    outbound_ip = requests.get("https://api.ipify.org").text
    logging.info(f"⚡ Current outbound IP (for whitelist in Coinbase Advanced): {outbound_ip}")
except Exception as e:
    logging.warning(f"⚠️ Unable to fetch outbound IP: {e}")

# --- Verify PEM can sign data ---
try:
    dummy = b"test"
    signature = private_key.sign(dummy, ec.ECDSA(hashes.SHA256()))
    logging.info("✅ PEM can sign data (ready for JWT).")
except Exception as e:
    logging.error(f"❌ PEM failed signing test: {e}")
    exit(1)

# --- Placeholder: Connect to Coinbase API ---
def fetch_accounts():
    """
    Replace this with actual Coinbase REST call using JWT auth.
    For now, placeholder returns dummy account list.
    """
    return [{"id": "dummy_account_1", "currency": "USD"}]

# --- Auto-select account ---
if not TRADING_ACCOUNT_ID:
    accounts = fetch_accounts()
    if accounts:
        TRADING_ACCOUNT_ID = accounts[0]["id"]
        logging.info(f"✅ Auto-selected trading account: {TRADING_ACCOUNT_ID}")
    else:
        logging.warning("⚠️ No accounts found automatically. Set TRADING_ACCOUNT_ID env var.")

# --- Main trading loop ---
def trading_loop():
    logging.info("Entering trading loop...")
    while True:
        try:
            # --- Replace this with actual trade logic ---
            logging.info(f"Checking signals... (LIVE_TRADING={LIVE_TRADING})")
            if LIVE_TRADING:
                logging.info("🚀 Placing trades now (placeholder)")
            else:
                logging.info("⚠️ Dry-run mode: no trades executed.")
            time.sleep(10)
        except KeyboardInterrupt:
            logging.info("Trading loop stopped manually.")
            break
        except Exception as e:
            logging.error(f"Error in trading loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logging.info("🔥 Coinbase PEM and API key check complete. Bot ready to start trading.")
    trading_loop()
