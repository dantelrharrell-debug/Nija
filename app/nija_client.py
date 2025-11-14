# app/nija_client.py
import os
from coinbase.rest import RESTClient
from loguru import logger
import time

logger.remove()
logger.add(lambda m: print(m, end=""))

ORG = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")   # should be full resource path (organizations/.../apiKeys/...)
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

logger.info("\n=== nija_client start ===\n")
if not (ORG and API_KEY and PEM_RAW):
    logger.error("Missing one of COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_PEM_CONTENT")
else:
    # fix literal \n -> actual newlines if provider encoded them
    if "\\n" in PEM_RAW:
        PEM = PEM_RAW.replace("\\n", "\n")
    else:
        PEM = PEM_RAW

    # ensure trailing newline (some parsers expect it)
    if not PEM.endswith("\n"):
        PEM = PEM + "\n"

    logger.info(f"ENV lengths: ORG={len(ORG)} API_KEY={len(API_KEY)} PEM={len(PEM)}")

    # Initialize SDK REST client
    try:
        client = RESTClient(api_key=API_KEY, api_secret=PEM)
        logger.success("RESTClient initialized.")
    except Exception as e:
        logger.error(f"RESTClient init error: {e}")
        client = None

    # Test endpoints and print response headers/body with trace-id for Coinbase support
    if client:
        tests = [
            ("v2_accounts", "https://api.coinbase.com/v2/accounts"),
            ("brokerage_org_accounts", f"https://api.coinbase.com/api/v3/brokerage/organizations/{ORG}/accounts")
        ]
        headers = {"CB-VERSION": "2025-11-13", "User-Agent": "nija/validator"}
        for name, url in tests:
            try:
                # Do a raw requests call using the SDK's auth or just use client if SDK has method:
                # Use requests here so we can inject the SDK-generated token if needed later.
                from requests import get
                # build a lightweight JWT using SDK (SDK's client should sign inside get_accounts, but we'll call raw)
                # For now call the SDK method if available:
                if name == "v2_accounts":
                    resp = client.get_accounts()
                    logger.info(f"{name} -> type={type(resp)}")
                    logger.info(str(resp)[:1000])
                else:
                    # raw GET using RESTClient.session if present (fallback)
                    resp = client.session.get(url, headers=headers, timeout=10)
                    logger.info(f"{name} -> status {resp.status_code}")
                    logger.info("Headers: " + str(dict(resp.headers)))
                    logger.info("Body: " + resp.text[:1000].replace('\\n','\\n'))
            except Exception as e:
                logger.error(f"Request {name} error: {e}")

logger.info("\n=== nija_client end ===\n")
