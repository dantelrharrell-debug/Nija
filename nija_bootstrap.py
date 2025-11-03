# -----------------------------
# nija_pem_bootstrap.py
# -----------------------------
import os
import logging
from threading import Thread
from nija_app import nija_worker  # your existing worker loop
from nija_client import init_client  # your Coinbase client init

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_pem_bootstrap")

# -----------------------------
# Step 1: Read and format PEM
# -----------------------------
PEM_STRING = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_STRING:
    logger.error("[NIJA-PEM] COINBASE_PEM_CONTENT not set in Render secrets!")
    raise SystemExit(1)

# Fix escaped newlines from Render secret
PEM_STRING = PEM_STRING.replace("\\n", "\n")

# Ensure proper header/footer
if not PEM_STRING.startswith("-----BEGIN PRIVATE KEY-----"):
    PEM_STRING = "-----BEGIN PRIVATE KEY-----\n" + PEM_STRING
if not PEM_STRING.endswith("-----END PRIVATE KEY-----"):
    PEM_STRING = PEM_STRING + "\n-----END PRIVATE KEY-----"

# Optional: enforce 64-char lines for body
lines = ["-----BEGIN PRIVATE KEY-----"]
body = PEM_STRING.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "").replace("\n", "")
for i in range(0, len(body), 64):
    lines.append(body[i:i+64])
lines.append("-----END PRIVATE KEY-----")
formatted_pem = "\n".join(lines)

# Write PEM to temporary file
PEM_PATH = "/tmp/coinbase.pem"
with open(PEM_PATH, "w") as f:
    f.write(formatted_pem)
os.chmod(PEM_PATH, 0o600)
logger.info(f"[NIJA-PEM] PEM written successfully to {PEM_PATH}")

# -----------------------------
# Step 2: Initialize client
# -----------------------------
client = init_client(pem_path=PEM_PATH)
logger.info("[NIJA-PEM] Coinbase client initialized ✅")

# -----------------------------
# Step 3: Start worker in background
# -----------------------------
worker_thread = Thread(target=nija_worker, daemon=True)
worker_thread.start()
logger.info("[NIJA-PEM] Worker started in background ✅")

# -----------------------------
# Step 4: Flask app for Gunicorn
# -----------------------------
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija is live"
