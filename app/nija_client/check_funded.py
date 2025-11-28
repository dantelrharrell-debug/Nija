# app/nija_client/check_funded.py
import os
import logging

logger = logging.getLogger(__name__)

def check_funded_accounts() -> bool:
    """
    Return True if at least one funded account is available.
    Replace with your real check against Coinbase or your broker.
    For now this reads an env flag or returns True (safe default).
    """
    # quick env override: set CHECK_FUNDED_STRICT=1 to require actual funded accounts
    strict = os.environ.get("CHECK_FUNDED_STRICT", "0") == "1"
    # Example quick-check: if FUNDING_OK env present treat as funded
    if os.environ.get("FUNDING_OK", ""):
        logger.info("FUNDING_OK env set, treating as funded.")
        return True

    if not strict:
        # Non-strict default: allow startup (prevents infinite crash loop while developing).
        logger.info("check_funded_accounts non-strict mode: allowing start. Set CHECK_FUNDED_STRICT=1 for strict behavior.")
        return True

    # Strict mode placeholder: return False to fail container startup unless real logic added.
    logger.error("Strict funded-check enabled but no funded accounts found. Set FUNDING_OK=1 for testing.")
    return False
