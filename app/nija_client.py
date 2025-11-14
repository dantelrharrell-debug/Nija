# app/nija_client.py
import os
import base64
import logging
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# env
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")   # could be "organizations/.../apiKeys/..."
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")   # optional, may contain literal "\n"
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "")      # optional: single-line base64 of PEM
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0")

# 1) Resolve PEM: prefer COINBASE_PEM_CONTENT, else decode PEM_B64
def resolve_pem():
    if PEM_RAW:
        # fix literal \n -> real newlines
        if "\\n" in PEM_RAW:
            logger.info("Fixing escaped newlines in COINBASE_PEM_CONTENT")
            return PEM_RAW.replace("\\n", "\n")
        return PEM_RAW
    if PEM_B64:
        try:
            raw = base64.b64decode(PEM_B64)
            return raw.decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to decode COINBASE_PEM_B64: {e}")
            return None
    return None

PEM = resolve_pem()

# 2) Validate presence
if not ORG_ID:
    logger.error("COINBASE_ORG_ID is missing")
if not API_KEY:
    logger.error("COINBASE_API_KEY is missing")
if not PEM:
    logger.error("No PEM available (COINBASE_PEM_CONTENT or COINBASE_PEM_B64 required)")

# 3) Normalize API_KEY to full resource path
if API_KEY and "organizations/" in API_KEY:
    API_KEY_PATH = API_KEY
else:
    API_KEY_PATH = f"organizations/{ORG_ID}/apiKeys/{API_KEY}" if ORG_ID and API_KEY else API_KEY

logger.info(f"Using API key path: {API_KEY_PATH if API_KEY_PATH else '<missing>'}")
logger.info(f"PEM length: {len(PEM) if PEM else 'None'}")
logger.info(f"LIVE_TRADING={LIVE_TRADING}")

# 4) Try to construct a client using Coinbase SDK (if installed)
try:
    from coinbase.rest import RESTClient
    SDK_OK = True
except Exception:
    RESTClient = None
    SDK_OK = False
    logger.warning("coinbase.rest RESTClient not available in this container (pip package missing?)")

client = None
if SDK_OK and API_KEY_PATH and PEM:
    try:
        client = RESTClient(api_key=API_KEY_PATH, api_secret=PEM)
    except Exception as e:
        logger.error(f"Failed to instantiate RESTClient: {type(e).__name__}: {e}")

# 5) Test connection
def test_accounts():
    if not client:
        logger.error("No client available, skipping test_accounts()")
        return False
    try:
        accounts = client.get_accounts()
        logger.success("✅ Coinbase accounts fetched (preview):")
        for a in accounts.data[:5]:
            logger.info(f"- {a.id}  balance={getattr(a,'balance',None)} name={getattr(a,'name',None)}")
        return True
    except Exception as e:
        logger.error(f"Coinbase API test failed: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    ok = test_accounts()
    if ok:
        logger.info("AUTH OK — bot would be allowed to trade (check LIVE_TRADING).")
    else:
        logger.info("AUTH FAILED — fix env keys / PEM and redeploy.")
