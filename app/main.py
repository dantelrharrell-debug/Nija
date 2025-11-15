# main.py — entry point for Railway
import os
import sys
import time
from datetime import datetime
from loguru import logger
from app.nija_client import CoinbaseClient

# ----------------------------
# 1️⃣ Setup logger
# ----------------------------
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting... (main.py)")

def log(msg):
    """Timestamped log helper"""
    ts = datetime.utcnow().isoformat() + "Z"
    logger.info(f"{ts} | {msg}")

# ----------------------------
# 2️⃣ Debug starter checks
# ----------------------------
log(f"MAIN: cwd={os.getcwd()} pid={os.getpid()}")

# List directories for debugging
for p in [".", "/app", "/tmp", "/workspace", "/home"]:
    try:
        items = os.listdir(p)
        log(f"LS {p}: {items[:10]}")
    except Exception as e:
        log(f"LS {p} failed: {e}")

# Write indicator file to /tmp
try:
    with open("/tmp/nija_started.ok", "a") as f:
        f.write(datetime.utcnow().isoformat() + " started\n")
    log("WROTE /tmp/nija_started.ok")
except Exception as e:
    log(f"WRITE FAILED: {e}")

# ----------------------------
# 3️⃣ Initialize Coinbase client
# ----------------------------
try:
    pem_clean = os.environ["COINBASE_PEM_CONTENT"]
    client = CoinbaseClient(
        api_key=os.environ["COINBASE_API_KEY"],
        org_id=os.environ["COINBASE_ORG_ID"],
        pem=pem_clean
    )
    log("CoinbaseClient initialized")
except Exception as e:
    logger.exception("Failed to initialize CoinbaseClient")
    sys.exit(1)

# ----------------------------
# 4️⃣ Optional: test Coinbase API
# ----------------------------
try:
    response = client.request("GET", "https://api.coinbase.com/v2/accounts")
    log(f"Coinbase API test status: {response.status_code}")
    if response.status_code != 200:
        log(f"API response: {response.text}")
except Exception as e:
    logger.exception("Coinbase test request failed")

# ----------------------------
# 5️⃣ Import and start bot
# ----------------------------
try:
    from app.start_bot_main import start_bot_main
    log("Imported start_bot_main OK")
    start_bot_main()
except Exception as e:
    logger.exception("Bot crashed")

# ----------------------------
# 6️⃣ HEARTBEAT loop
# ----------------------------
log("Entering HEARTBEAT loop (every 5s)")
while True:
    log("HEARTBEAT - container alive")
    time.sleep(5)
