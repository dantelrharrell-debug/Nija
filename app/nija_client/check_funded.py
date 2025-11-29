# app/nija_client/check_funded.py
import os

def check_funded_accounts() -> bool:
    """
    Minimal stub. Replace with real funded-account logic.
    Returns True if any funded account detected, False otherwise.
    """
    # Example: prefer an env var for quick tests
    if os.environ.get("FORCE_FUNDED") == "1":
        return True

    # Insert actual Coinbase/account checks here. For now:
    # - return True when FUNDING_OK=1 env var set
    return os.environ.get("FUNDING_OK", "0") == "1"
