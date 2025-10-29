# import_fallbacks.py (put at top of nija_client.py)
import importlib, logging, inspect, sys
logger = logging.getLogger(__name__)

def debug_coinbase_import():
    try:
        m = importlib.import_module("coinbase_advanced_py")
        logger.info(f"Imported coinbase_advanced_py module: {m}")
        logger.info(f"module __file__: {getattr(m, '__file__', None)}")
        logger.info(f"module __path__: {getattr(m, '__path__', None)}")
        logger.info(f"available attrs (sample): {sorted([a for a in dir(m) if a.lower().startswith('coin') or 'client' in a.lower() or 'coinbase' in a.lower()])[:40]}")
        if hasattr(m, "CoinbaseClient"):
            logger.info("CoinbaseClient found on coinbase_advanced_py")
            return m.CoinbaseClient
    except Exception as e:
        logger.exception("Direct import coinbase_advanced_py failed: %s", e)

    # try import forms used in different code bases
    for try_name in [
        "coinbase_advanced_py.client",
        "coinbase_advanced_py.client.client",
        "coinbase_advanced_py.client_client",
    ]:
        try:
            m = importlib.import_module(try_name)
            logger.info(f"Imported {try_name}: {m}; file={getattr(m, '__file__', None)}")
            # try common attribute names
            for attr in ("CoinbaseClient", "CoinbaseAdvancedClient", "CoinbaseClientV1"):
                if hasattr(m, attr):
                    logger.info(f"Found {attr} in {try_name}")
                    return getattr(m, attr)
        except Exception:
            pass

    logger.error("No usable Coinbase client class found in coinbase_advanced_py package. Check package version or shadowing files.")
    return None

CoinbaseClient = debug_coinbase_import()
if CoinbaseClient is None:
    raise ImportError("Cannot locate CoinbaseClient in coinbase_advanced_py; see logs for details.")
