#!/usr/bin/env python3
# entrypoint_check.py
import os
import logging
import traceback

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija.entrypoint_check")

def masked(val):
    if not val:
        return None
    # show only first/last 4 chars
    s = str(val)
    return s[:4] + "..." + s[-4:]

def check_env_vars():
    keys = [
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",         # pasted PEM (less preferred)
        "COINBASE_API_SECRET_PATH",    # path to uploaded PEM file (preferred)
        "COINBASE_API_PASSPHRASE",
        "SANDBOX",
        "LOG_LEVEL"
    ]
    log.info("Checking environment variables (masked):")
    for k in keys:
        v = os.getenv(k)
        display = masked(v) if v else None
        log.info("  %s = %s", k, display)
    return {k: os.getenv(k) for k in keys}

def try_read_pem(path):
    if not path:
        log.info("COINBASE_API_SECRET_PATH not set; skipping file read.")
        return False
    try:
        with open(path, "r") as f:
            head = f.readline().strip()
            # don't print contents, only check header/footer presence
            content = f.read()
            ok = head.startswith("-----BEGIN")
            log.info("PEM file read at path: %s ; header_ok=%s", path, ok)
            return ok
    except Exception as e:
        log.error("Failed to read PEM at %s: %s", path, e)
        return False

def try_import_coinbase_pkg():
    try:
        import importlib
        pkg = importlib.import_module("coinbase_advanced_py")
        log.info("coinbase_advanced_py import: OK (module: %s)", getattr(pkg, "__file__", str(pkg)))
        # try to import client submodule if available
        try:
            
            log.info("coinbase_advanced_py.client import: OK")
            return True
        except Exception as e:
            log.warning("coinbase_advanced_py.client import: FAILED (%s)", e)
            return True  # package exists — client submodule might be a different name/constructor
    except Exception as e:
        log.error("coinbase_advanced_py import: FAILED (%s)", e)
        return False

def attempt_client_init(env):
    """
    Try to construct CoinbaseClient without making network calls.
    This uses the same env vars as your nija_client.py. It will not perform trades.
    """
    try:
        # prefer PEM file path, else direct secret
        api_key = env.get("COINBASE_API_KEY")
        api_secret = env.get("COINBASE_API_SECRET")
        secret_path = env.get("COINBASE_API_SECRET_PATH")
        passphrase = env.get("COINBASE_API_PASSPHRASE")
        sandbox = env.get("SANDBOX", "true").lower() in ("1","true","yes")

        if not api_key:
            log.warning("COINBASE_API_KEY missing; cannot init client.")
            return False

        if not api_secret and secret_path:
            try:
                with open(secret_path, "r") as f:
                    api_secret = f.read()
                    log.info("Loaded API secret from file path (not printed).")
            except Exception as e:
                log.error("Failed to read COINBASE_API_SECRET_PATH: %s", e)
                return False

        if not api_secret:
            log.warning("No API secret available (COINBASE_API_SECRET or COINBASE_API_SECRET_PATH).")
            return False

        # Try importing the client with safe guard
        try:
            
            # Try instantiating with given values (some clients validate PEM immediately)
            try:
                obj = CoinbaseClient(api_key=api_key, api_secret=api_secret, api_passphrase=passphrase, sandbox=sandbox)
                log.info("CoinbaseClient constructor succeeded (object created).")
                # do NOT call any network methods
                return True
            except Exception as e:
                log.warning("CoinbaseClient constructor raised (could be PEM formatting): %s", e)
                return False
        except Exception as e:
            log.error("Failed to import CoinbaseClient: %s", e)
            return False

    except Exception:
        log.error("Unexpected error in attempt_client_init:\n%s", traceback.format_exc())
        return False

if __name__ == "__main__":
    log.info("=== NIJA ENTRYPOINT CHECK START ===")
    env = check_env_vars()
    pkg_ok = try_import_coinbase_pkg()
    pem_ok = try_read_pem(env.get("COINBASE_API_SECRET_PATH"))
    client_ok = attempt_client_init(env)
    log.info("SUMMARY: package_ok=%s, pem_read_ok=%s, client_init_ok=%s", pkg_ok, pem_ok, client_ok)
    if pkg_ok and (pem_ok or env.get("COINBASE_API_SECRET")) and client_ok:
        log.info("=== ENTRYPOINT CHECK: PASS — Coinbase client should initialize on startup ===")
    else:
        log.warning("=== ENTRYPOINT CHECK: FAIL — check logs above; typical fixes: upload PEM as secret file, set COINBASE_API_SECRET_PATH, ensure COINBASE_API_KEY set ===")
