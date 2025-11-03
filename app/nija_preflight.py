#!/usr/bin/env python3
"""
NIJA Preflight: Checks Coinbase credentials and USD Spot balance.
"""

import logging
from nija_client import get_usd_spot_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check...")

amt, acct = get_usd_spot_balance()

if acct:
    logger.info(f"[NIJA-PREFLIGHT] USD Spot balance detected: {amt} in account '{acct.get('name')}'")
    logger.info("[NIJA-PREFLIGHT] Preflight complete — ready for live trading ✅")
else:
    logger.error("[NIJA-PREFLIGHT] No USD Spot balance detected or Coinbase credentials missing ❌")
    raise RuntimeError("No USD Spot balance detected or Coinbase credentials missing")
