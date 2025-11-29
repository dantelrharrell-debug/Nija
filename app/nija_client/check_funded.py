# app/nija_client/check_funded.py
import os

def check_funded_accounts() -> bool:
    """
    Replace this with your real funding-check logic.
    For now, check FUNDING_OK or FORCE_FUNDED env var to allow deploy tests.
    """
    if os.getenv("FORCE_FUNDED") == "1":
        return True
    if os.getenv("FUNDING_OK") == "1":
        return True

    # TODO: implement real checks e.g. coinbase client query
    return False
