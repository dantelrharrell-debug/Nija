# -----------------------------
# nija_write_pem.py
# -----------------------------
import os
import logging
from nija_client import init_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_pem")

# Read PEM string from Render secret
PEM_STRING = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_STRING:
    logger.error("[NIJA-PEM] COINBASE_PEM_CONTENT is not set in Render secrets!")
    raise SystemExit(1)

# Ensure proper formatting
if not PEM_STRING.startswith("-----BEGIN PRIVATE KEY-----"):
    PEM_STRING = "-----BEGIN PRIVATE KEY-----\n" + PEM_STRING
if not PEM_STRING.endswith("-----END PRIVATE KEY-----"):
    PEM_STRING = PEM_STRING + "\n-----END PRIVATE KEY-----"

# Fix internal line breaks (64 chars per line)
lines = ["-----BEGIN PRIVATE KEY-----"]
body = PEM_STRING.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "").replace("\n", "")
for i in range(0, len(body), 64):
    lines.append(body[i:i+64])
lines.append("-----END PRIVATE KEY-----")
formatted_pem = "\n".join(lines)

# Write to temporary PEM file for Nija
PEM_PATH = "/tmp/coinbase.pem"
with open(PEM_PATH, "w") as f:
    f.write(formatted_pem)

os.chmod(PEM_PATH, 0o600)
logger.info(f"[NIJA-PEM] PEM written successfully to {PEM_PATH}")

# Initialize Coinbase client
client = init_client(pem_path=PEM_PATH)
logger.info("[NIJA-PEM] Coinbase client initialized successfully ✅")
