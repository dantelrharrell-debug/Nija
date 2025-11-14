# app/nija_client.py
import os
import logging
import base64
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

API_KEY = os.environ.get("COINBASE_API_KEY", "")
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "")

def load_pem():
    if PEM_B64:
        try:
            pem = base64.b64decode(PEM_B64).decode()
            logger.info("Loaded PEM from COINBASE_PEM_B64.")
            return pem
        except Exception as e:
            logger.error(f"Failed to decode COINBASE_PEM_B64: {e}")
    if "\\n" in PEM_RAW:
        logger.info("Replacing literal \\n to real newlines in COINBASE_PEM_CONTENT.")
        return PEM_RAW.replace("\\n", "\n")
    return PEM_RAW

PEM = load_pem()
logger.info(f"PEM length: {len(PEM) if PEM else 'None'}")

# detect if API_KEY already contains full organizations/... path
if "organizations/" in API_KEY:
    SUB = API_KEY
else:
    if ORG_ID and API_KEY:
        SUB = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"
    else:
        SUB = API_KEY

# Try to use Coinbase SDK if present
try:
    from coinbase.rest import RESTClient
    sdk_ok = True
except Exception as e:
    logger.warning(f"Coinbase SDK not available: {e}")
    RESTClient = None
    sdk_ok = False

if sdk_ok:
    try:
        client = RESTClient(api_key=SUB, api_secret=PEM)
        accounts = client.get_accounts()
        logger.success("✅ Coinbase accounts fetched (via SDK).")
        for a in accounts.data:
            logger.info(f"{a.id} | {a.name} | {a.balance.amount} {a.balance.currency}")
    except Exception as e:
        logger.error(f"SDK call failed: {e}")
        # fall through to let debug_jwt_info examine further
else:
    logger.info("SDK not used; use debug_jwt_info.py to validate key / JWT manually.")
