# -----------------------------
# nija_app.py (LIVE RENDER READY)
# -----------------------------
import os
import time
import logging
from decimal import Decimal
from nija_client import init_client, get_usd_balance  # your existing helper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# -----------------------------
# Step 1: Write PEM file from Render secret
# -----------------------------
PEM_STRING = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_STRING:
    logger.error("[NIJA-PEM] COINBASE_PEM_CONTENT not set in Render secrets!")
    raise SystemExit(1)

# Format PEM properly
if not PEM_STRING.startswith("-----BEGIN PRIVATE KEY-----"):
    PEM_STRING = "-----BEGIN PRIVATE KEY-----\n" + PEM_STRING
if not PEM_STRING.endswith("-----END PRIVATE KEY-----"):
    PEM_STRING = PEM_STRING + "\n-----END PRIVATE KEY-----"

lines = ["-----BEGIN PRIVATE KEY-----"]
body = PEM_STRING.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "").replace("\n", "")
for i in range(0, len(body), 64):
    lines.append(body[i:i+64])
lines.append("-----END PRIVATE KEY-----")
formatted_pem = "\n".join(lines)

# Write PEM to temporary path
PEM_PATH = "/tmp/coinbase.pem"
with open(PEM_PATH, "w") as f:
    f.write(formatted_pem)
os.chmod(PEM_PATH, 0o600)
logger.info(f"[NIJA-PEM] PEM written successfully to {PEM_PATH}")

# -----------------------------
# Step 2: Initialize Coinbase client
# -----------------------------
client = init_client(pem_path=PEM_PATH)
logger.info("[NIJA-APP] Coinbase client initialized ✅")

# -----------------------------
# Step 3: Preflight check
# -----------------------------
try:
    balance = get_usd_balance(client)
    logger.info(f"[NIJA-APP] Preflight check passed. USD Balance: {balance}")
except Exception as e:
    logger.error(f"[NIJA-APP] Failed preflight check: {e}")
    raise SystemExit("[NIJA] Fix Coinbase credentials or PEM before running.")

# -----------------------------
# Step 4: Define worker loop
# -----------------------------
def nija_worker():
    logger.info("[NIJA-WORKER] Starting live worker loop...")
    while True:
        try:
            balance = get_usd_balance(client)
            logger.info(f"[NIJA-WORKER] USD Balance: {balance}")

            # Example trade logic (replace with actual strategy)
            if balance > 10:
                logger.info("[NIJA-WORKER] Ready to trade. Add BUY/SELL logic here.")

            time.sleep(5)  # adjust frequency
        except KeyboardInterrupt:
            logger.info("[NIJA-WORKER] KeyboardInterrupt received. Stopping worker.")
            break
        except Exception as e:
            logger.exception(f"[NIJA-WORKER] Error in worker loop: {e}")
            time.sleep(5)

# -----------------------------
# Step 5: Flask endpoint for health check
# -----------------------------
from flask import Flask
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija is live"

# -----------------------------
# Step 6: Run everything
# -----------------------------
if __name__ == "__main__":
    logger.info("[NIJA-APP] Starting live bot...")
    nija_worker()
