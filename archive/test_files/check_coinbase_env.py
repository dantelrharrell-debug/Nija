import os
import logging

logging.basicConfig(level=logging.INFO)

# --- Load Coinbase env variables ---
PEM = os.getenv("COINBASE_PEM_CONTENT")
API_KEY = os.getenv("COINBASE_API_KEY_ID")
ORG_ID = os.getenv("COINBASE_ORG_ID")

# --- Verify PEM and API Key presence ---
if PEM and API_KEY and ORG_ID:
    logging.info("✅ PEM loaded and API key & org ID present")
else:
    logging.error("❌ Check PEM formatting, API key, or org ID")

# --- Optional PEM parsing check ---
try:
    from cryptography.hazmat.primitives import serialization
    private_key = serialization.load_pem_private_key(
        PEM.encode("utf-8"),
        password=None,
    )
    logging.info("✅ PEM parsed successfully")
except Exception as e:
    logging.error(f"❌ Failed to parse PEM: {e}")
