# main.py  (entry file)
import os
import sys
import time
from loguru import logger
from datetime import datetime
from app.nija_client import CoinbaseClient

logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting...")

def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    logger.info(f"{ts} | {msg}")

log(f"MAIN: cwd={os.getcwd()} pid={os.getpid()}")

# list directories for container debug (keeps Railway logs informative)
for p in [".", "/app", "/tmp", "/workspace", "/home"]:
    try:
        items = os.listdir(p)
        log(f"LS {p}: {items[:10]}")
    except Exception as e:
        log(f"LS {p} failed: {e}")

# Build CoinbaseClient from env
api_key = os.getenv("COINBASE_API_KEY")
org_id = os.getenv("COINBASE_ORG_ID")
pem = os.getenv("COINBASE_PEM_CONTENT") or os.getenv("COINBASE_PEM_B64")
kid = os.getenv("COINBASE_JWT_KID")

client = None
try:
    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, kid=kid, sandbox=True)
    log("CoinbaseClient initialized")
except Exception as e:
    logger.exception("Failed to init CoinbaseClient")
    # fatal: stop here so we don't continue in broken auth state
    sys.exit(1)

# Test that JWT-based auth is appropriate for the endpoint you're hitting.
# IMPORTANT: if you want to talk to REST v2 endpoints (api.coinbase.com/v2/*) you must use the REST key/HMAC scheme,
# not JWT bearer. This test will show whether the JWT-auth call to the sandbox accounts endpoint succeeds.
try:
    resp = client.sandbox_accounts()
    log(f"Coinbase API test status: {resp.status_code}")
    log(f"API response: {resp.text[:1000]}")
    if resp.status_code == 401:
        log("Received 401. Check: (1) are you calling an endpoint that expects JWT bearer tokens or HMAC API key headers? (2) PEM/kid/sub correctness.")
except Exception as e:
    logger.exception("Coinbase test request failed")

# Now import and run main bot function (assuming it accepts client)
try:
    from app.start_bot_main import start_bot_main
    log("Imported start_bot_main OK")
    # Many earlier logs showed start_bot_main requires client parameter — pass it:
    start_bot_main(client)
except TypeError:
    # fallback: some versions expect no args — try both
    try:
        start_bot_main()
    except Exception:
        logger.exception("start_bot_main failed in both calling styles")
except Exception:
    logger.exception("Bot crashed")

# heartbeat so Railway logs show activity quickly.
while True:
    log("HEARTBEAT - container alive")
    time.sleep(5)
