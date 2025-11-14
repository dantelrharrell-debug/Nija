# nija_client.py
import os, base64
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# env vars
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "")

def load_pem():
    pem = ""

    # Priority 1 — raw PEM
    if PEM_RAW and "-----BEGIN" in PEM_RAW:
        pem = PEM_RAW

    # Priority 2 — base64 PEM
    elif PEM_B64:
        try:
            pem = base64.b64decode(PEM_B64).decode()
        except Exception as e:
            logger.error(f"Failed to decode PEM_B64: {e}")

    # Fix encoded newlines
    pem = pem.replace("\\n", "\n")

    # Guarantee ending newline
    if pem and not pem.endswith("\n"):
        pem += "\n"

    return pem

PEM = load_pem()
logger.info(f"PEM length: {len(PEM) if PEM else 0}")

# Build full API key path
if API_KEY.startswith("organizations/"):
    API_KEY_FULL = API_KEY
else:
    API_KEY_FULL = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"

logger.info(f"API key length: {len(API_KEY_FULL)}")

# Import Coinbase
try:
    from coinbase.rest import RESTClient
    SDK_OK = True
except Exception as e:
    logger.error(f"Coinbase SDK import failed: {e}")
    SDK_OK = False
    RESTClient = None

client = None

if SDK_OK and PEM and API_KEY_FULL:
    try:
        client = RESTClient(api_key=API_KEY_FULL, api_secret=PEM)
        logger.info("RESTClient created successfully.")
    except Exception as e:
        logger.error(f"RESTClient creation failed: {e}")
else:
    logger.error("Missing PEM or API key — cannot create RESTClient.")

def test_accounts():
    if not client:
        logger.error("No client available.")
        return

    try:
        acc = client.get_accounts()
        logger.success(f"Fetched accounts: {len(acc.data)}")
    except Exception as e:
        logger.error(f"Account test failed: {e}")

if __name__ == "__main__":
    test_accounts()
