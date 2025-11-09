# nija_app.py
import os
import sys
import time
from loguru import logger

# --- START: Advanced/JWT Coinbase startup ---
logger = logger.bind(name="nija_startup")

# Try to import the advanced client
ADV_CLIENT_IMPORT_PATH = "nija_coinbase_advanced"  # change to "app.nija_coinbase_advanced" if inside app/
try:
    cb_adv = __import__(ADV_CLIENT_IMPORT_PATH, fromlist=["*"])
    logger.info("Advanced Coinbase client imported successfully")
except Exception as e:
    cb_adv = None
    logger.error(f"Failed to import advanced client: {e}")
    sys.exit(1)

# Determine auth mode: prefer explicit env, otherwise detect PEM presence
auth_mode_env = os.getenv("COINBASE_AUTH_MODE", "").lower()
pem_content = os.getenv("COINBASE_PEM_CONTENT", "") or ""
pem_path = os.getenv("COINBASE_PRIVATE_KEY_PATH", "") or ""
has_pem = bool(pem_content.strip()) or bool(pem_path.strip())

use_advanced = False
if auth_mode_env in ("advanced", "jwt"):
    use_advanced = True
elif auth_mode_env in ("hmac", "legacy", "exchange"):
    use_advanced = False
else:
    use_advanced = has_pem

logger.info("Startup: COINBASE_AUTH_MODE='%s', has_pem=%s -> use_advanced=%s",
            auth_mode_env, has_pem, use_advanced)

# Initialize client
if use_advanced:
    if not cb_adv:
        logger.error("Advanced client module missing; cannot start bot")
        sys.exit(1)
    try:
        # Perform a key permissions check
        resp = cb_adv.get_key_permissions()
        logger.info(f"Coinbase Advanced key permissions status: {getattr(resp, 'status_code', None)}")
        logger.info(f"Coinbase Advanced permissions body (truncated): {(getattr(resp, 'text','') or '')[:1000]}")
        if getattr(resp, "status_code", None) != 200:
            logger.error("Coinbase Advanced auth failed; check PEM, key ID, or BASE_URL")
            sys.exit(1)
    except Exception as e:
        logger.exception(f"Coinbase Advanced startup check failed: {e}")
        sys.exit(1)

    # Set client for later use in bot
    client = cb_adv
    logger.info("Coinbase Advanced JWT auth OK — client ready")
else:
    logger.error("HMAC auth mode selected or no PEM found; this version only supports Advanced/JWT")
    sys.exit(1)
# --- END Advanced/JWT Coinbase startup ---

# Example function: list accounts
def list_accounts():
    try:
        accounts_resp = client.get_accounts()  # This uses advanced client method
        # Some advanced clients return .json() or .text
        if hasattr(accounts_resp, "json"):
            accounts_data = accounts_resp.json()
        else:
            accounts_data = accounts_resp  # assume already dict/list

        for acc in accounts_data.get("accounts", accounts_data):
            logger.info(f"Account: {acc.get('name')} | Balance: {acc.get('balance', {}).get('amount')} {acc.get('balance', {}).get('currency')}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

# Example function: live trading loop placeholder
def live_trading_loop():
    logger.info("Starting live trading loop...")
    while True:
        try:
            # Placeholder for your trading logic
            logger.info("Checking for trading signals...")
            time.sleep(5)  # Replace with your actual trading interval
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    list_accounts()          # Optional: list accounts on start
    live_trading_loop()      # Start live trading
