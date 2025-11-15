import os
import sys
import time
from loguru import logger
from datetime import datetime
from app.nija_client import CoinbaseClient

# Setup logger
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting...")

# Helper log with timestamp
def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    logger.info(f"{ts} | {msg}")

log(f"MAIN: cwd={os.getcwd()} pid={os.getpid()}")

# List directories for debug
for p in [".", "/app", "/tmp", "/workspace", "/home"]:
    try:
        items = os.listdir(p)
        log(f"LS {p}: {items[:10]}")
    except Exception as e:
        log(f"LS {p} failed: {e}")

# Write indicator file
try:
    with open("/tmp/nija_started.ok", "a") as f:
        f.write(datetime.utcnow().isoformat() + " started\n")
    log("WROTE /tmp/nija_started.ok")
except Exception as e:
    log(f"WRITE FAILED: {e}")

# --- Initialize Coinbase client safely ---
try:
    pem_raw = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_raw:
        raise ValueError("COINBASE_PEM_CONTENT missing in environment")

    pem_clean = pem_raw.replace("\\n", "\n")  # fix newline issues
    api_key = os.environ.get("COINBASE_API_KEY")
    org_id = os.environ.get("COINBASE_ORG_ID")

    if not api_key or not org_id:
        raise ValueError("COINBASE_API_KEY or COINBASE_ORG_ID missing")

    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem_clean)
    log("CoinbaseClient initialized")

    # Optional: test API connection immediately
    resp = client.request("GET", "https://api.coinbase.com/v2/accounts")
    log(f"Coinbase API test status: {resp.status_code}")
    if resp.status_code != 200:
        log(f"API response: {resp.text}")
        raise ValueError("Coinbase API unauthorized. Check key, PEM, org, and permissions.")

except Exception as e:
    logger.exception("Failed to initialize CoinbaseClient. Bot will not start.")
    sys.exit(1)  # stop container if credentials are bad

# --- Start bot ---
try:
    from app.start_bot_main import start_bot_main
    log("Imported start_bot_main OK")
    start_bot_main(client)  # pass client to bot
except Exception as e:
    logger.exception("Bot crashed during start")

# Heartbeat loop so container stays alive
log("Entering HEARTBEAT loop (every 5s)")
while True:
    log("HEARTBEAT - container alive")
    time.sleep(5)
