# app/nija_client.py
import os, base64
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# env vars
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "")

def get_pem():
    # prefer raw PEM if looks valid
    if PEM_RAW and "-----BEGIN" in PEM_RAW:
        pem = PEM_RAW
    elif PEM_B64:
        try:
            pem = base64.b64decode(PEM_B64.encode()).decode()
        except Exception as e:
            logger.error("Failed to base64-decode COINBASE_PEM_B64: " + str(e))
            pem = PEM_RAW or ""
    else:
        pem = PEM_RAW or ""

    # fix literal "\n" sequences
    if "\\n" in pem:
        pem = pem.replace("\\n", "\n")

    if pem and not pem.endswith("\n"):
        pem = pem + "\n"
    return pem

PEM = get_pem()
logger.info(f"PEM length: {len(PEM) if PEM else 'MISSING'}")

# build full API key resource path if needed
if API_KEY and "organizations/" in API_KEY:
    API_KEY_FULL = API_KEY
else:
    API_KEY_FULL = f"organizations/{ORG_ID}/apiKeys/{API_KEY}" if ORG_ID and API_KEY else API_KEY

logger.info(f"API key length: {len(API_KEY_FULL) if API_KEY_FULL else 'MISSING'}")

# Attempt to import Coinbase SDK
try:
    from coinbase.rest import RESTClient
    SDK_OK = True
except Exception as e:
    RESTClient = None
    SDK_OK = False
    logger.warning("Coinbase SDK not available: " + str(e))

client = None
if SDK_OK and PEM and API_KEY_FULL:
    try:
        client = RESTClient(api_key=API_KEY_FULL, api_secret=PEM)
        logger.info("RESTClient instantiated.")
    except Exception as e:
        logger.error("Failed to instantiate RESTClient: " + str(e))

def test_accounts():
    if not client:
        logger.error("No Coinbase client available; check SDK and env vars.")
        return
    try:
        accounts = client.get_accounts()
        logger.success("✅ Accounts fetched; count: " + str(len(getattr(accounts, "data", []))))
        for a in accounts.data:
            logger.info(f"- {getattr(a, 'id', '')} | {getattr(a, 'name', 'no-name')} | {getattr(a, 'balance', '')}")
    except Exception as e:
        logger.error("❌ Coinbase API call failed: " + str(e))

if __name__ == "__main__":
    test_accounts()
