# main.py (debug import helper)
import os
import sys
import traceback
from loguru import logger
from pathlib import Path
import importlib.util

logger.configure(level=os.environ.get("LOG_LEVEL", "DEBUG"))

def list_dir(path):
    try:
        entries = sorted([p.name for p in Path(path).iterdir()])
        return entries
    except Exception as e:
        return f"<err listing {path}: {e}>"

def try_import_statement(stmt):
    try:
        logger.info("Trying import: %s", stmt)
        exec(stmt, globals())
        logger.success("Import succeeded: %s", stmt)
        return True
    except Exception:
        logger.error("Import failed: %s\n%s", stmt, traceback.format_exc())
        return False

def try_dynamic_load(filepath, modname):
    p = Path(filepath)
    if not p.exists():
        logger.warning("File %s does not exist", filepath)
        return False
    try:
        logger.info("Attempting dynamic import of %s as module '%s'", filepath, modname)
        spec = importlib.util.spec_from_file_location(modname, str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        globals()[modname] = mod
        logger.success("Dynamically loaded %s -> module '%s'", filepath, modname)
        return True
    except Exception:
        logger.error("Dynamic import failed for %s\n%s", filepath, traceback.format_exc())
        return False

def main():
    logger.info("=== DEBUG: runtime info ===")
    logger.info("cwd: %s", os.getcwd())
    logger.info("sys.executable: %s", sys.executable)
    logger.info("sys.path:\n%s", "\n".join(sys.path))

    root = Path(".").resolve()
    logger.info("Root path: %s", root)

    logger.info("Root dir listing: %s", list_dir(root))
    app_dir = root / "app"
    logger.info("'app' dir exists? %s", app_dir.exists())
    if app_dir.exists():
        logger.info("'app' dir listing: %s", list_dir(app_dir))

    # Show potential nija_client locations
    candidates = [
        root / "nija_client.py",
        app_dir / "nija_client.py",
        root / "app" / "nija_client.py",
    ]
    for c in candidates:
        logger.info("Candidate: %s -> exists=%s", c, c.exists())

    # Try direct import first (root)
    if try_import_statement("from nija_client import CoinbaseClient"):
        logger.success("Use import: from nija_client import CoinbaseClient")
        return

    # Try package import (app.nija_client)
    if try_import_statement("from app.nija_client import CoinbaseClient"):
        logger.success("Use import: from app.nija_client import CoinbaseClient")
        return

    # If not available, try dynamic load from known file paths
    for idx, cand in enumerate(candidates):
        if cand.exists():
            modname = f"nija_client_dynamic_{idx}"
            if try_dynamic_load(cand, modname):
                # try to get CoinbaseClient inside loaded module
                mod = globals()[modname]
                if hasattr(mod, "CoinbaseClient"):
                    logger.success("Found CoinbaseClient in %s", cand)
                    globals()["CoinbaseClient"] = getattr(mod, "CoinbaseClient")
                    # minimal test call (won't run external calls)
                    try:
                        logger.info("Instantiating CoinbaseClient for smoke test (no args)...")
                        client = getattr(mod, "CoinbaseClient")()
                        logger.info("Instantiated client object: %s", type(client))
                    except Exception:
                        logger.warning("Instantiating client failed (maybe needs env vars). Trace:\n%s", traceback.format_exc())
                    return
                else:
                    logger.warning("Module %s loaded but CoinbaseClient not found inside", cand)

    # Last resort: tell user exactly what to change
    logger.error(
        "Could not import nija_client. Fix options:\n"
        "1) Put nija_client.py at project root so 'from nija_client import CoinbaseClient' works.\n"
        "2) Put files in 'app/' and add an __init__.py; then import 'from app.nija_client import CoinbaseClient'.\n"
        "3) Ensure Dockerfile COPY copies the file (no .dockerignore blocking it).\n"
        "4) If using a package, ensure working directory is correct and PYTHONPATH includes project root."
    )

if __name__ == "__main__":
    main()
