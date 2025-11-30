# nija_client.py
import os
import logging
import textwrap

# -------------------------
# Logging setup
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# -------------------------
# Environment variables
# -------------------------
CDP_API_KEY = os.getenv("CDP_API_KEY")
CDP_API_SECRET = os.getenv("CDP_API_SECRET")
CDP_API_SECRET_FILE = os.getenv("CDP_API_SECRET_FILE")

# -------------------------
# Load PEM secret helper
# -------------------------
def load_pem_secret():
    """
    Load PEM private key from either CDP_API_SECRET or CDP_API_SECRET_FILE.
    Preserves newlines and trims whitespace.
    """
    if CDP_API_SECRET:
        logger.info("Using CDP_API_SECRET from environment.")
        pem = CDP_API_SECRET.replace("\\n", "\n")
        return pem.strip() + ("\n" if not pem.endswith("\n") else "")
    if CDP_API_SECRET_FILE:
        logger.info(f"Loading PEM from CDP_API_SECRET_FILE: {CDP_API_SECRET_FILE}")
        try:
            with open(CDP_API_SECRET_FILE, "r", encoding="utf-8") as f:
                pem = f.read()
                return pem.strip() + ("\n" if not pem.endswith("\n") else "")
        except Exception as e:
            logger.exception("Failed to read CDP_API_SECRET_FILE: %s", e)
            return None
    logger.warning("No CDP_API_SECRET or CDP_API_SECRET_FILE set.")
    return None

# -------------------------
# Build Coinbase client
# -------------------------
def build_client():
    """
    Attempts to instantiate a Coinbase Advanced (CDP) client.
    Provides fallback guidance if import fails.
    """
    api_key = CDP_API_KEY
    api_secret = load_pem_secret()

    if not api_key:
        raise RuntimeError("Missing CDP_API_KEY environment variable.")
    if not api_secret:
        raise RuntimeError(
            "Missing CDP_API_SECRET or CDP_API_SECRET_FILE environment variable or file."
        )

    # Primary import path
    try:
        from coinbase_advanced.client import Client as CoinbaseClient
        logger.info("Imported Client from coinbase_advanced.client")
        return CoinbaseClient(api_key=api_key, api_secret=api_secret)
    except Exception as e1:
        logger.debug("Import coinbase_advanced.client.Client failed: %s", e1)

    # Alternate import path
    try:
        from coinbase.client import RESTClient as CoinbaseClient2
        logger.info("Imported RESTClient from coinbase.client")
        return CoinbaseClient2(api_key=api_key, api_secret=api_secret)
    except Exception as e2:
        logger.debug("Import coinbase.client.RESTClient failed: %s", e2)

    # Top-level fallback
    try:
        import coinbase_advanced as cba
        logger.info("Imported coinbase_advanced top-level module, attempting fallback client.")
        if hasattr(cba, "Client"):
            return cba.Client(api_key=api_key, api_secret=api_secret)
        if hasattr(cba, "RESTClient"):
            return cba.RESTClient(api_key=api_key, api_secret=api_secret)
    except Exception as e3:
        logger.debug("Top-level import fallback failed: %s", e3)

    # If all fails
    raise RuntimeError(
        textwrap.dedent("""
        Could not import a compatible Coinbase Advanced (CDP) client from installed packages.
        Make sure 'coinbase-advanced-py' or the official SDK is installed in the same Python environment.
        Use: pip install coinbase-advanced-py
        """)
    )

# -------------------------
# Initialize client
# -------------------------
try:
    client = build_client()
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    client = None

# -------------------------
# Check funds
# -------------------------
def check_funds():
    """
    Returns a dictionary of all available balances.
    Example: {'USD': '100.50', 'BTC': '0.0012'}
    """
    if client is None:
        logger.error("Coinbase client not initialized.")
        return {}

    try:
        accounts = client.get_accounts()
        balances = {acc['currency']: acc['balance']['amount'] for acc in accounts}
        logger.info(f"Fetched balances: {balances}")
        return balances
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return {}
