# app/validate_coinbase_env.py
import os, textwrap
from loguru import logger
logger.remove()
logger.add(lambda m: print(m, end=""))

def first_lines(s, n=3):
    if not s:
        return "<missing>"
    return "\\n".join(s.splitlines()[:n])

ORG = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

logger.info("=== Coinbase env validator ===\\n")
logger.info(f"COINBASE_ORG_ID: {'present' if ORG else 'MISSING'}")
logger.info(f"COINBASE_API_KEY: {'present' if API_KEY else 'MISSING'}")
if API_KEY:
    logger.info(f"COINBASE_API_KEY preview: {API_KEY[:80]}{'...' if len(API_KEY) > 80 else ''}")
    if not API_KEY.startswith("organizations/"):
        logger.warning("API key does not start with 'organizations/'. It should be the full resource path.")

logger.info(f"COINBASE_PEM_CONTENT: length={len(PEM_RAW) if PEM_RAW else 'MISSING'}")
if PEM_RAW:
    # show only a safe preview of first line to verify formatting
    fl = first_lines(PEM_RAW, n=1)
    logger.info(f"PEM first line preview: {fl[:200]}")
    if not fl.startswith("-----BEGIN"):
        logger.error("PEM does not start with -----BEGIN -- looks mis-pasted. Should start with -----BEGIN EC PRIVATE KEY-----")
    if "\\n" in PEM_RAW:
        logger.warning("PEM contains literal \\n sequences. Your code should replace('\\\\n', '\\n') before use.")

logger.info("\\nNext recommended steps:")
logger.info("1) Confirm COINBASE_API_KEY is the full resource path: organizations/<org-id>/apiKeys/<uuid>")
logger.info("2) Confirm the PEM you pasted is the one shown when that API key was created in Coinbase Advanced.")
logger.info("3) If unsure, create a new API key, copy the PEM immediately, update envs, and redeploy.")
