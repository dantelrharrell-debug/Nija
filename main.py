import os, sys, time
from loguru import logger
from datetime import datetime
from app.nija_client import CoinbaseClient

# ------------------------------
# Setup logger
# ------------------------------
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting...")

# ------------------------------
# Debug helper
# ------------------------------
def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    logger.info(f"{ts} | {msg}")

log(f"MAIN: cwd={os.getcwd()} pid={os.getpid()}")

# ------------------------------
# List some key directories
# ------------------------------
for p in [".", "/app", "/tmp", "/workspace", "/home"]:
    try:
        items = os.listdir(p)
        log(f"LS {p}: {items[:10]}")
    except Exception as e:
        log(f"LS {p} failed: {e}")

# ------------------------------
# Write indicator file
# ------------------------------
try:
    with open("/tmp/nija_started.ok", "a") as f:
        f.write(datetime.utcnow().isoformat() + " started\n")
    log("WROTE /tmp/nija_started.ok")
except Exception as e:
    log(f"WRITE FAILED: {e}")

# ------------------------------
# Initialize Coinbase client
# ------------------------------
pem_clean = os.environ.get("COINBASE_PEM_CONTENT", "").replace("\\n", "\n")
client = CoinbaseClient(
    api_key=os.environ.get("COINBASE_API_KEY"),
    org_id=os.environ.get("COINBASE_ORG_ID"),
    pem=pem_clean
)
log("CoinbaseClient initialized")

# ------------------------------
# Optional: test API connection
# ------------------------------
try:
    response = client.request("GET", "https://api.coinbase.com/v2/accounts")
    log(f"Coinbase API test status: {response.status_code}")
    if response.status_code != 200:
        log(f"API response: {response.text}")
except Exception as e:
    logger.exception("Coinbase test request failed")

# ------------------------------
# Import and start bot
# ------------------------------
try:
    from app.start_bot_main import start_bot_main
    log("Imported start_bot_main OK")
    start_bot_main(client)  # Pass the client now
except Exception as e:
    logger.exception("Bot crashed during start")

# ------------------------------
# HEARTBEAT loop
# ------------------------------
log("Entering HEARTBEAT loop (every 5s)")
while True:
    log("HEARTBEAT - container alive")
    time.sleep(5)
