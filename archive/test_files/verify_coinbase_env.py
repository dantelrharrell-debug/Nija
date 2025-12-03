import os
import logging
from coinbase.wallet.client import Client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("verify_env")

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")
api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

# Mask keys for display
masked_key = api_key[:4] + "****" if api_key else None
masked_secret = api_secret[:4] + "****" if api_secret else None

log.info(f"COINBASE_API_KEY: {masked_key}")
log.info(f"COINBASE_API_SECRET: {masked_secret}")
log.info(f"COINBASE_API_PASSPHRASE: {'set' if api_passphrase else '(empty)'}")

if not all([api_key, api_secret]):
    log.error("Missing API credentials in environment!")
    raise SystemExit(1)

# Replace \n sequences with real newlines for Coinbase compatibility
if "\\n" in api_secret:
    api_secret = api_secret.replace("\\n", "\n")

client = Client(api_key, api_secret)

try:
    accounts = client.get_accounts()
    data = accounts.get("data", [])
    log.info(f"✅ Connected to Coinbase. {len(data)} account(s) found.")
except Exception as e:
    log.error(f"❌ Connection failed: {type(e).__name__} – {e}")
