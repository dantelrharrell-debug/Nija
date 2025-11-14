# app/nija_client.py
import os
import base64
import logging
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# env vars
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")   # raw PEM with newlines
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "")       # base64 single-line

# 1) obtain a sane PEM string (BEGIN..END with \n lines)
def get_pem():
    # prefer raw PEM if it looks valid
    if PEM_RAW and "-----BEGIN" in PEM_RAW:
        pem = PEM_RAW
    elif PEM_B64:
        try:
            decoded = base64.b64decode(PEM_B64.encode())
            pem = decoded.decode()
        except Exception as e:
            logger.error(f"Failed to base64-decode COINBASE_PEM_B64: {e}")
            pem = ""
    else:
        pem = ""

    # if railway/UI placed literal "\n" sequences, convert them
    if pem and "\\n" in pem:
        pem = pem.replace("\\n", "\n")

    # ensure trailing newline for some loaders
    if pem and not pem.endswith("\n"):
        pem = pem + "\n"

    return pem

PEM = get_pem()
logger.info(f"PEM length: {len(PEM) if PEM else 'MISSING'}")

# 2) build full API key resource path if necessary
if API_KEY and "organizations/" in API_KEY:
    API_KEY_FULL = API_KEY
else:
    if ORG_ID and API_KEY:
        API_KEY_FULL = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"
    else:
        API_KEY_FULL = API_KEY  # leave as-is (maybe already full path or empty)

logger.info(f"API_KEY length: {len(API_KEY_FULL)} (use full path?)")

# 3) init Coinbase REST client (if sdk present)
try:
    from coinbase.rest import RESTClient  # Coinbase Advanced SDK
    SDK_OK = True
except Exception as e:
    RESTClient = None
    SDK_OK = False
    logger.warning("Coinbase REST SDK not available in container: " + str(e))

client = None
if SDK_OK and PEM and API_KEY_FULL:
    try:
        client = RESTClient(api_key=API_KEY_FULL, api_secret=PEM)
        logger.info("RESTClient created (attempting accounts test...)")
    except Exception as e:
        logger.error("Failed to create RESTClient: " + str(e))

# 4) test fetch accounts
def test_accounts():
    if not client:
        logger.error("No REST client available; check SDK and env vars.")
        return
    try:
        accounts = client.get_accounts()
        logger.success("✅ Accounts fetched; count: " + str(len(getattr(accounts, "data", []))))
        for a in accounts.data:
            logger.info(f"- {a.id} | {getattr(a, 'name', 'no-name')} | {getattr(a, 'balance', '')}")
    except Exception as e:
        logger.error("❌ Coinbase API call failed: " + str(e))

if __name__ == "__main__":
    test_accounts()
