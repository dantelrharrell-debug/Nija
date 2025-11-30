import logging
import importlib

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

Client = None
_client_module = None

# Try names in order until one succeeds
for pkg_name in ("coinbase_advanced", "coinbase_advanced_py", "coinbase_advanced.client", "coinbase_advanced_py.client"):
    short = pkg_name.split('.')[0]
    try:
        _client_module = importlib.import_module(short)
        # If the package is the top-level and contains client, import client if needed
        if not hasattr(_client_module, "Client") and hasattr(_client_module, "client"):
            # maybe package exposes submodule client; try importing it
            try:
                client_sub = importlib.import_module(f"{short}.client")
                if hasattr(client_sub, "Client"):
                    Client = getattr(client_sub, "Client")
            except Exception:
                pass
        else:
            # maybe __init__ exposes Client or submodule
            if hasattr(_client_module, "Client"):
                Client = getattr(_client_module, "Client")
        logger.info("Using vendored Coinbase package: %s", short)
        break
    except Exception as e:
        logger.debug("Import %s failed: %s", pkg_name, e)

# Final attempt: import exact client module path if not found yet
if Client is None:
    try:
        client_sub = importlib.import_module("coinbase_advanced.client")
        if hasattr(client_sub, "Client"):
            Client = getattr(client_sub, "Client")
            logger.info("Loaded coinbase_advanced.client")
    except Exception:
        logger.debug("coinbase_advanced.client not available")

if Client is None:
    logger.error("coinbase_advanced NOT available — live trading disabled")
else:
    logger.info("coinbase Client available: %s", Client)
