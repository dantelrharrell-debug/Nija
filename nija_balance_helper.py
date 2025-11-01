import os
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import logging

logger = logging.getLogger("nija_balance_helper")

PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # raw PEM string from Render secret

def get_pem_file():
    if not PEM_CONTENT:
        logger.error("[NIJA-BALANCE] PEM content missing!")
        return None

    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_file.write(PEM_CONTENT.encode("utf-8"))
    tmp_file.close()
    return tmp_file.name

def check_pem_file(path: str):
    try:
        with open(path, "rb") as pem_file:
            key_data = pem_file.read()
            serialization.load_pem_private_key(
                key_data,
                password=None,
                backend=default_backend()
            )
        logger.info(f"[NIJA-BALANCE] PEM file loaded successfully ✅")
        return True
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to load PEM file: {e}")
        return False

# --- Preflight check ---
pem_file_path = get_pem_file()
if not pem_file_path or not check_pem_file(pem_file_path):
    logger.error("[NIJA-BALANCE] Aborting: fix your PEM file before running the bot.")
