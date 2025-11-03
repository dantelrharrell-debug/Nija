# -----------------------------
# nija_bootstrap.py
# -----------------------------
import os
import logging
from threading import Thread
from flask import Flask

# Import your worker loop and client initializer
from nija_app import nija_worker
from nija_client import init_client, get_usd_balance  # Make sure your client has this function

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_bootstrap")

# -----------------------------
# Step 1: Write PEM file from Render secret
# -----------------------------
PEM_STRING = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_STRING:
    logger.error("[NIJA-BOOTSTRAP] COINBASE_PEM_CONTENT not set!")
    raise SystemExit(1)

# Ensure proper line breaks
PEM_STRING = PEM_STRING.replace("\\n", "\n")
PEM_PATH = "/tmp/coinbase.pem"

with open(PEM_PATH, "w") as f:
    f.write(PEM_STRING)

os.chmod(PEM_PATH, 0o600)
logger.info(f"[NIJA-BOOTSTRAP] PEM written to {PEM_PATH}")

# -----------------------------
# Step 2: Initialize Coinbase client
# -----------------------------
client = init_client(pem_path=PEM_PATH)
logger.info("[NIJA-BOOTSTRAP] Coinbase client initialized ✅")

# -----------------------------
# Step 2a: Check USD balance before starting worker
# -----------------------------
usd_balance = get_usd_balance(client)
logger.info(f"[NIJA-BOOTSTRAP] USD Balance: {usd_balance}")

# Optional: stop bot if no funds
if usd_balance <= 0:
    logger.warning("[NIJA-BOOTSTRAP] USD balance is 0 — trading will not start.")
else:
    # -----------------------------
    # Step 3: Start worker in background
    # -----------------------------
    worker_thread = Thread(target=nija_worker, daemon=True)
    worker_thread.start()
    logger.info("[NIJA-BOOTSTRAP] Worker started in background ✅")

# -----------------------------
# Step 4: Flask app for Gunicorn
# -----------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return f"Nija is live. USD Balance: {usd_balance}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
