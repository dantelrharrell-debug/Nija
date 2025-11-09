# nija_app.py
import os
import sys
import time
from loguru import logger

# --- START: Advanced/JWT Coinbase startup ---
logger = logger.bind(name="nija_startup")

# Import the advanced client
ADV_CLIENT_IMPORT_PATH = "nija_coinbase_advanced"  # adjust to "app.nija_coinbase_advanced" if inside app/
try:
    cb_adv = __import__(ADV_CLIENT_IMPORT_PATH, fromlist=["*"])
    logger.info("Advanced Coinbase client imported successfully")
except Exception as e:
    cb_adv = None
    logger.error(f"Failed to import advanced client: {e}")
    sys.exit(1)

# Determine auth mode
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
        resp = cb_adv.get_key_permissions()
        logger.info(f"Coinbase Advanced key permissions status: {getattr(resp, 'status_code', None)}")
        logger.info(f"Coinbase Advanced permissions body (truncated): {(getattr(resp, 'text','') or '')[:1000]}")
        if getattr(resp, "status_code", None) != 200:
            logger.error("Coinbase Advanced auth failed; check PEM, key ID, or BASE_URL")
            sys.exit(1)
    except Exception as e:
        logger.exception(f"Coinbase Advanced startup check failed: {e}")
        sys.exit(1)

    client = cb_adv
    logger.info("Coinbase Advanced JWT auth OK — client ready")
else:
    logger.error("HMAC auth mode selected or no PEM found; this version only supports Advanced/JWT")
    sys.exit(1)
# --- END Advanced/JWT Coinbase startup ---

# List accounts function
def list_accounts():
    try:
        resp = client.get_accounts()
        # Ensure JSON dict
        if hasattr(resp, "json"):
            data = resp.json()
        else:
            data = resp
        accounts = data.get("accounts", data)
        for acc in accounts:
            bal = acc.get("balance", {})
            logger.info(f"Account: {acc.get('name')} | Balance: {bal.get('amount')} {bal.get('currency')}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

# Live trading loop placeholder
def live_trading_loop():
    logger.info("Starting live trading loop...")
    while True:
        try:
            # Example: fetch balances every 5 seconds (placeholder)
            resp = client.get_accounts()
            if hasattr(resp, "json"):
                data = resp.json()
            else:
                data = resp
            accounts = data.get("accounts", data)
            for acc in accounts:
                bal = acc.get("balance", {})
                logger.info(f"[LIVE CHECK] {acc.get('name')}: {bal.get('amount')} {bal.get('currency')}")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    list_accounts()
    live_trading_loop()
