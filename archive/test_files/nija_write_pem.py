# -----------------------------
# nija_write_pem.py
# -----------------------------
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_write_pem")

# Fetch PEM from environment
PEM_ENV = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_ENV:
    logger.error("[NIJA-PEM] COINBASE_PEM_CONTENT not set!")
    raise SystemExit(1)

# Remove whitespace and replace literal "\n" with newlines
PEM_ENV = PEM_ENV.strip().replace("\\n", "\n")

# Ensure proper header/footer
if not PEM_ENV.startswith("-----BEGIN PRIVATE KEY-----"):
    PEM_ENV = "-----BEGIN PRIVATE KEY-----\n" + PEM_ENV
if not PEM_ENV.endswith("-----END PRIVATE KEY-----"):
    PEM_ENV += "\n-----END PRIVATE KEY-----"

# Write PEM to temporary path
PEM_PATH = "/tmp/coinbase.pem"
with open(PEM_PATH, "w") as f:
    f.write(PEM_ENV)

# Secure file permissions
os.chmod(PEM_PATH, 0o600)
logger.info(f"[NIJA-PEM] PEM written successfully to {PEM_PATH}")
