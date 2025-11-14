# app/pem_quick_check.py
import os
from loguru import logger
logger.remove(); logger.add(lambda m: print(m,end=""))

pem = os.environ.get("COINBASE_PEM_CONTENT","")
b64 = os.environ.get("COINBASE_PEM_B64","")
logger.info(f"COINBASE_PEM_B64 present: {bool(b64)}")
logger.info(f"COINBASE_PEM_CONTENT length: {len(pem)}")
if "\\n" in pem and "\n" not in pem:
    logger.info("PEM appears to have literal \\n sequences.")
if pem:
    lines = [l for l in pem.splitlines() if l.strip()]
    if lines:
        logger.info("Header line: "+repr(lines[0]))
        logger.info("Footer line: "+repr(lines[-1]))
