# app/pem_quick_check.py
import os
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove(); logger.add(lambda m: print(m, end=""))

pem_raw = os.environ.get("COINBASE_PEM_CONTENT","")
pem_b64 = os.environ.get("COINBASE_PEM_B64","")
logger.info("PEM_B64 present: %s", bool(pem_b64))
logger.info("PEM_CONTENT length: %d", len(pem_raw))
if pem_raw:
    logger.info("PEM first line: %r", pem_raw.splitlines()[0] if pem_raw.splitlines() else "")
    logger.info("PEM last line:  %r", pem_raw.splitlines()[-1] if pem_raw.splitlines() else "")
# try to load
pem = None
if pem_b64 and not pem_raw:
    import base64
    try:
        pem = base64.b64decode(pem_b64).decode()
        logger.info("Decoded PEM_B64 length: %d", len(pem))
    except Exception as e:
        logger.error("Failed to decode PEM_B64: %s", e)
elif pem_raw:
    if "\\n" in pem_raw:
        pem = pem_raw.replace("\\n","\n")
    else:
        pem = pem_raw

if pem:
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())
        pub = key.public_key().public_bytes(encoding=serialization.Encoding.PEM,
                                           format=serialization.PublicFormat.SubjectPublicKeyInfo)
        logger.info("✅ Private key parsed. Public key preview: %s", pub.decode().splitlines()[:3])
    except Exception as e:
        logger.error("Failed to parse PEM: %s: %s", type(e).__name__, e)
else:
    logger.error("No PEM available to test.")
