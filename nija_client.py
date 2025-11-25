import os
import logging
import time

# ===============================
# LOGGING SETUP
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ===============================
# COINBASE ENVIRONMENT SETUP
# ===============================
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# Verify that all env vars exist
missing = []
for name, value in [
    ("API_KEY", COINBASE_API_KEY),
    ("API_SECRET", COINBASE_API_SECRET),
    ("API_SUB", COINBASE_API_SUB),
    ("PEM_CONTENT", COINBASE_PEM_CONTENT)
]:
    if not value:
        missing.append(name)

if missing:
    logging.error(f"Missing Coinbase environment variables: {', '.join(missing)}")
    LIVE_TRADING = False
else:
    LIVE_TRADING = True

# Optional masked logging for debug
def mask(s, visible=6):
    return s[:visible] + "..." + s[-visible:] if s else "<MISSING>"

logging.info(f"COINBASE_API_KEY: {mask(COINBASE_API_KEY)}")
logging.info(f"COINBASE_API_SECRET: {mask(COINBASE_API_SECRET)}")
logging.info(f"COINBASE_API_SUB: {mask(COINBASE_API_SUB)}")
logging.info(f"COINBASE_PEM_CONTENT present? {bool(COINBASE_PEM_CONTENT)}")
logging.info(f"Live trading enabled? {LIVE_TRADING}")

# ===============================
# COINBASE CLIENT INITIALIZATION
# ===============================
if LIVE_TRADING:
    try:
        from coinbase_advanced_py import CoinbaseAdvancedClient

        client = CoinbaseAdvancedClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_SUB,
            pem_content=COINBASE_PEM_CONTENT,
        )

        logging.info("✅ Coinbase client successfully initialized for live trading.")
    except Exception as e:
        logging.error(f"⚠️ Failed to initialize Coinbase client: {e}")
        client = None
        LIVE_TRADING = False
else:
    logging.warning("⚠️ Live trading disabled due to missing environment variables.")
    client = None

# ===============================
# UTILITY: TEST CONNECTION
# ===============================
def test_coinbase_connection():
    if not client:
        logging.warning("Coinbase client not initialized. Cannot test connection.")
        return False
    try:
        account_info = client.get_accounts()
        logging.info(f"Coinbase connection test successful. Accounts retrieved: {len(account_info)}")
        return True
    except Exception as e:
        logging.error(f"Coinbase connection test failed: {e}")
        return False

# Example usage (can be called from Flask app on startup)
if __name__ == "__main__":
    test_coinbase_connection()
