# nija_client.py
import os
import logging
import textwrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Environment variable names expected:
# CDP_API_KEY  => organizations/{org_id}/apiKeys/{key_id}
# CDP_API_SECRET  => PEM private key string (multi-line) OR
# CDP_API_SECRET_FILE => path to PEM file (recommended for containers / secrets)
CDP_API_KEY = os.getenv("CDP_API_KEY")
CDP_API_SECRET = os.getenv("CDP_API_SECRET")
CDP_API_SECRET_FILE = os.getenv("CDP_API_SECRET_FILE")

def load_pem_secret():
    if CDP_API_SECRET:
        logger.info("Using CDP_API_SECRET from environment.")
        # preserve newlines if user stored with \n sequences
        pem = CDP_API_SECRET
        # if the stored PEM was single-line with literal '\n', convert to real newlines
        if "\\n" in pem:
            pem = pem.replace("\\n", "\n")
        # strip trailing/leading whitespace but keep PEM markers intact
        return pem.strip() + ("\n" if not pem.endswith("\n") else "")
    if CDP_API_SECRET_FILE:
        logger.info("Loading PEM from CDP_API_SECRET_FILE: %s", CDP_API_SECRET_FILE)
        try:
            with open(CDP_API_SECRET_FILE, "r", encoding="utf-8") as f:
                pem = f.read()
                return pem.strip() + ("\n" if not pem.endswith("\n") else "")
        except Exception as e:
            logger.exception("Failed to read CDP_API_SECRET_FILE: %s", e)
            return None
    logger.warning("No CDP_API_SECRET or CDP_API_SECRET_FILE environment variables set.")
    return None

def build_client():
    """
    Try multiple possible client import paths to maximize compatibility with
    different coinbase-advanced python package versions/distributions.
    Returns an instantiated client or raises an informative exception.
    """
    api_key = CDP_API_KEY
    api_secret = load_pem_secret()

    if not api_key:
        raise RuntimeError("Missing CDP_API_KEY environment variable.")
    if not api_secret:
        raise RuntimeError("Missing CDP_API_SECRET (or CDP_API_SECRET_FILE) environment variable or file.")

    # try common import paths (most reliable: coinbase_advanced.client.Client)
    try:
        # Most likely path (based on coinbase-advanced-py)
        from coinbase_advanced.client import Client as CoinbaseClient
        logger.info("Imported Client from coinbase_advanced.client")
        return CoinbaseClient(api_key=api_key, api_secret=api_secret)
    except Exception as e1:
        logger.debug("Import coinbase_advanced.client.Client failed: %s", e1)

    try:
        # Alternate package name used by some distributions
        from coinbase.client import RESTClient as CoinbaseClient2
        logger.info("Imported RESTClient from coinbase.client")
        return CoinbaseClient2(api_key=api_key, api_secret=api_secret)
    except Exception as e2:
        logger.debug("Import coinbase.client.RESTClient failed: %s", e2)

    # Last resort: attempt to import top-level module and inspect
    try:
        import coinbase_advanced as cba
        logger.info("Imported coinbase_advanced top-level module, attempting to instantiate default client.")
        # some versions expose a factory or default client class
        if hasattr(cba, "Client"):
            return cba.Client(api_key=api_key, api_secret=api_secret)
        if hasattr(cba, "RESTClient"):
            return cba.RESTClient(api_key=api_key, api_secret=api_secret)
    except Exception as e3:
        logger.debug("Top-level import fallback failed: %s", e3)

    # If we get here, we can't instantiate an SDK client
    raise RuntimeError(
        textwrap.dedent("""
        Could not import a compatible Coinbase Advanced (CDP) client from installed packages.
        Make sure 'coinbase-advanced-py' or the official SDK is installed in the same Python environment.
        pip list | grep coinbase
        If you're using a different package name/version, adapt nija_client.build_client() accordingly.
        """)
    )
