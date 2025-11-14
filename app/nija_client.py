# app/nija_client.py
import os
import time
from loguru import logger

# optional: use Coinbase SDK if available
try:
    from coinbase.rest import RESTClient
    SDK_AVAILABLE = True
except Exception:
    RESTClient = None
    SDK_AVAILABLE = False

logger.remove()
logger.add(lambda m: print(m, end=""))

logger.info("=== nija_client debug start ===\n")

ORG = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

# Basic presence checks
logger.info(f"COINBASE_ORG_ID: {'present' if ORG else 'MISSING'}")
logger.info(f"COINBASE_API_KEY: {'present' if API_KEY else 'MISSING'}")

if API_KEY:
    logger.info("COINBASE_API_KEY preview (first 120 chars):")
    logger.info(API_KEY[:120] + ("..." if len(API_KEY) > 120 else ""))
    if not API_KEY.startswith("organizations/"):
        logger.warning("API key does not start with 'organizations/'. Should be full resource path.")

# PEM checks
if not PEM_RAW:
    logger.error("COINBASE_PEM_CONTENT is MISSING")
else:
    # If Railway stored literal \n sequences, fix them
    if "\\n" in PEM_RAW:
        logger.warning("PEM contains literal \\n sequences, auto-replacing with newlines.")
        PEM = PEM_RAW.replace("\\n", "\n")
    else:
        PEM = PEM_RAW

    # Show safe preview of first/last lines
    lines = PEM.strip().splitlines()
    first = lines[0] if lines else "<empty>"
    last = lines[-1] if lines else "<empty>"
    logger.info(f"PEM first line preview: {first[:120]}")
    logger.info(f"PEM last line preview: {last[:120]}")
    if not first.startswith("-----BEGIN"):
        logger.error("PEM first line doesn't start with -----BEGIN ...")
    if not last.startswith("-----END"):
        logger.error("PEM last line doesn't end with -----END ...")

# Try SDK call if available
if SDK_AVAILABLE:
    logger.info("Coinbase SDK available. Attempting to initialize RESTClient...")
    try:
        client = RESTClient(api_key=API_KEY, api_secret=PEM)
        logger.info("RESTClient initialized. Attempting get_accounts() ...")
        try:
            accounts = client.get_accounts()
            logger.success("✅ Accounts fetched OK.")
            # show only ids/names (safe)
            for a in accounts.data:
                try:
                    aid = getattr(a, "id", "(id?)")
                    name = getattr(a, "name", "(name?)")
                    bal = getattr(getattr(a, "balance", None), "amount", "(bal?)")
                except Exception:
                    aid, name, bal = "(id?)", "(name?)", "(bal?)"
                logger.info(f"- {aid} | {name} | {bal}")
        except Exception as e:
            logger.error(f"API call failed: {type(e).__name__}: {e}")
    except Exception as e:
        logger.error(f"RESTClient init failed: {type(e).__name__}: {e}")
else:
    logger.warning("Coinbase SDK not available in the container. Install coinbase package to test SDK calls.")

logger.info("\n=== debug end ===")
