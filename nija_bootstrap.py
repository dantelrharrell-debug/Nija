# -----------------------------
# nija_bootstrap.py
# -----------------------------
import os
import logging
from threading import Thread
from nija_client import init_client  # your Coinbase client init
from nija_app import nija_worker    # your worker loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_bootstrap")

# -----------------------------
# Step 1: Write PEM file correctly
# -----------------------------
PEM_STRING = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_STRING:
    logger.error("[NIJA-BOOTSTRAP] COINBASE_PEM_CONTENT not set in environment!")
    raise SystemExit(1)

# Ensure proper line breaks
PEM_STRING = PEM_STRING.replace("\\n", "\n")

# Add BEGIN/END headers if missing
if not PEM_STRING.startswith("-----BEGIN PRIVATE KEY-----"):
    PEM_STRING = "-----BEGIN PRIVATE KEY-----\n" + PEM_STRING
if not PEM_STRING.endswith("-----END PRIVATE KEY-----"):
    PEM_STRING = PEM_STRING + "\n-----END PRIVATE KEY-----"

# Make sure body lines are 64 chars each (PEM standard)
lines = [PEM_STRING[:27]]  # keep the header intact
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
logger.info(f"[NIJA-BOOTSTRAP] PEM written successfully to {PEM_PATH}")

# -----------------------------
# Step 2: Initialize Coinbase client
# -----------------------------
client = init_client(pem_path=PEM_PATH)
logger.info("[NIJA-BOOTSTRAP] Coinbase client initialized ✅")

# -----------------------------
# Step 3: Start worker in background
# -----------------------------
worker_thread = Thread(target=nija_worker, daemon=True)
worker_thread.start()
logger.info("[NIJA-BOOTSTRAP] Worker started in background ✅")

# -----------------------------
# Step 4: Flask app entrypoint (Gunicorn)
# -----------------------------
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija is live"
