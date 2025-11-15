import os
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import sys

logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 200  # Coinbase PEMs are usually >200 bytes

def load_private_key_checked(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}. Make sure you uploaded the full PEM to your project.")
        sys.exit(1)

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < MIN_PEM_LENGTH:
        logger.error(f"PEM file is too short ({len(data)} bytes). This is likely truncated. JWT cannot be generated.")
        sys.exit(1)

    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded successfully.")
        return key
    except Exception as e:
        logger.exception("Failed to deserialize PEM private key: " + str(e))
        sys.exit(1)

# Usage example
if __name__ == "__main__":
    key = load_private_key_checked(PEM_FILE_PATH)
    logger.info(f"PEM file at {PEM_FILE_PATH} passed basic validation, ready for JWT generation.")
