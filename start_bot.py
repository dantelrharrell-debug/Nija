#!/usr/bin/env python3
# start_bot.py - robust loader that imports CoinbaseClient from app/nija_client.py by file path
import os
import sys
from loguru import logger
from pathlib import Path
import importlib.util

logger.remove()
logger.add(sys.stdout, level=os.getenv("LOG_LEVEL", "INFO"))

ROOT = Path(__file__).resolve().parent
APP_MODULE_PATH = ROOT / "app" / "nija_client.py"

def load_coinbaseclient_from_path(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"{path} not found (expected app/nija_client.py)")
    spec = importlib.util.spec_from_file_location("app_nija_client", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # may raise; we'll catch in caller
    if not hasattr(module, "CoinbaseClient"):
        raise ImportError("CoinbaseClient class not found in app/nija_client.py")
    return getattr(module, "CoinbaseClient")

def main():
    logger.info("Starting Nija HMAC/Advanced startup (robust loader).")
    try:
        # Prefer to load the app module directly by path (robust in any deploy layout)
        CoinbaseClient = load_coinbaseclient_from_path(APP_MODULE_PATH)
    except Exception as e:
        logger.exception("Failed to load CoinbaseClient from app/nija_client.py. Trying root nija_client.py as fallback.")
        # Fallback: try nija_client.py in repo root
        try:
            root_path = ROOT / "nija_client.py"
            CoinbaseClient = load_coinbaseclient_from_path(root_path)
        except Exception as e2:
            logger.exception("Fallback import failed. Cannot continue without CoinbaseClient.")
            return

    # Initialize client and check accounts
    try:
        client = CoinbaseClient(advanced=True)
    except Exception as e:
        logger.exception("Failed to initialize CoinbaseClient (JWT generation / env variables).")
        logger.error("Ensure COINBASE_ISS and COINBASE_PEM_CONTENT are set in your environment (and COINBASE_BASE if needed).")
        return

    try:
        accounts = client.fetch_advanced_accounts()
    except Exception:
        logger.exception("fetch_advanced_accounts() raised an exception.")
        accounts = []

    if not accounts:
        logger.error("No HMAC/Advanced accounts found. Verify key permissions and COINBASE_BASE/COINBASE_ISS/PEM.")
        return

    logger.info("Accounts:")
    for a in accounts:
        name = a.get("name") or a.get("id") or "<unknown>"
        bal = a.get("balance") or a.get("available") or {}
        logger.info(f" - {name} : {bal}")

    logger.info("✅ HMAC/Advanced account check complete. Bot ready to start trading loop (implement next).")

if __name__ == "__main__":
    main()
