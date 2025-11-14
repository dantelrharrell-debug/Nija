# app/pem_quick_check.py
import os
from loguru import logger
logger.remove(); logger.add(lambda m: print(m,end=""))
pem = os.environ.get("COINBASE_PEM_CONTENT","")
b64 = os.environ.get("COINBASE_PEM_B64","")
logger.info(f"PEM_B64 present: {bool(b64)}")
logger.info(f"PEM_CONTENT length: {len(pem)}")
if pem:
    logger.info("Header: "+repr(pem.splitlines()[0] if pem.splitlines() else ""))
    logger.info("Footer: "+repr(pem.splitlines()[-1] if pem.splitlines() else ""))
