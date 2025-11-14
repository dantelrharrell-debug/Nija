# app/debug_pem_analyzer.py
import os
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

pem_raw = os.environ.get("COINBASE_PEM_CONTENT", "")

logger.info("=== PEM ANALYZER START ===")
logger.info(f"Raw PEM length: {len(pem_raw)}")

# Fix escaped \n
if "\\n" in pem_raw:
    pem = pem_raw.replace("\\n", "\n")
else:
    pem = pem_raw

logger.info("Fixed PEM preview:")
logger.info(pem.splitlines()[0])
logger.info(pem.splitlines()[-1])

# Inspect every character
allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n- "
bad = []

for i, ch in enumerate(pem):
    if ch not in allowed:
        bad.append((i, ch))

if bad:
    logger.error("❌ BAD CHARACTERS FOUND IN PEM!")
    for idx, ch in bad[:20]:
        logger.error(f"Index {idx}: Invalid char → {repr(ch)}")
    logger.error("Fix these characters in COINBASE_PEM_CONTENT")
else:
    logger.info("✅ No invalid characters detected in PEM (formatting OK)")

logger.info("=== PEM ANALYZER END ===")
