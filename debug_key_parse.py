# debug_key_parse.py
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os

logger.remove()
logger.add(lambda m: print(m, end=""))

pem_raw = os.environ.get("COINBASE_PEM_CONTENT", "")
if "\\n" in pem_raw:
    pem = pem_raw.replace("\\n", "\n")
else:
    pem = pem_raw

if not pem:
    logger.error("COINBASE_PEM_CONTENT missing; try COINBASE_PEM_B64 instead.")
else:
    try:
        priv = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())
        pub = priv.public_key()
        pem_pub = pub.public_bytes(encoding=serialization.Encoding.PEM,
                                   format=serialization.PublicFormat.SubjectPublicKeyInfo)
        logger.info("✅ Private key loaded. Public key preview:")
        for ln in pem_pub.decode().splitlines()[:6]:
            logger.info(ln)
    except Exception as e:
        logger.error(f"Failed to load PEM: {type(e).__name__}: {e}")
