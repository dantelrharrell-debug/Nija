import logging
import importlib
import importlib.util
import traceback
import sys
import subprocess

# Optional: use importlib.metadata if available
try:
    from importlib import metadata as importlib_metadata
except ImportError:
    import importlib_metadata

logger = logging.getLogger(__name__)

# --- Coinbase diagnostic/factory ---
def _safe_pip_freeze():
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"],
            stderr=subprocess.STDOUT,
            timeout=30
        )
        return out.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("pip freeze failed: %s", e)
        return None

def _installed_coinbase_packages():
    found = []
    try:
        for dist in importlib_metadata.distributions():
            name = getattr(dist, "metadata", None) and dist.metadata.get("Name") or getattr(dist, "name", None)
            if name and "coinbase" in name.lower():
                found.append((name, getattr(dist, "version", "unknown")))
    except Exception:
        try:
            import pkg_resources
            for dist in pkg_resources.working_set:
                if "coinbase" in dist.project_name.lower():
                    found.append((dist.project_name, dist.version))
        except Exception:
            pass
    return found

def _try_import(name):
    try:
        return importlib.import_module(name), None
    except Exception as e:
        return None, e

def _find_spec(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

def get_coinbase_client(*args, **kwargs):
    """
    Attempts to import and instantiate a Coinbase client.
    Falls back to MockClient if SDK not installed.
    """
    logger.info("=== Coinbase SDK diagnostic start ===")
    logger.info("Installed coinbase packages: %s", _installed_coinbase_packages())
    pip_freeze = _safe_pip_freeze()
    if pip_freeze:
        logger.info("pip freeze (truncated 50 lines):\n%s", "\n".join(pip_freeze.splitlines()[:50]))

    # Candidate modules and client attributes
    candidates = [
        "coinbase_advanced", "coinbase_advanced.client", "coinbase", "coinbase.client"
    ]
    client_attrs = ["Client", "AdvancedClient", "CoinbaseClient", "CoinbaseAdvancedClient"]

    for mod_name in candidates:
        mod, err = _try_import(mod_name)
        if mod:
            for attr in client_attrs:
                client_obj = getattr(mod, attr, None)
                if client_obj:
                    try:
                        if callable(client_obj):
                            return client_obj(*args, **kwargs)
                        return client_obj
                    except Exception:
                        continue

    # Fallback mock client
    class MockClient:
        def __init__(self, *a, **k):
            logger.warning("Using MockClient for Coinbase — SDK not installed.")
        def list_accounts(self): return []
        def get_accounts(self): return []
        def accounts(self): return []
        def close(self): return None

    return MockClient()

# --- WSGI auto-exposure shim ---
def _expose_wsgi_app():
    """Ensure a top-level `app` callable exists for Gunicorn."""
    try:
        from flask import Flask, jsonify
    except ImportError:
        logger.warning("Flask not installed; cannot expose WSGI app.")
        return

    # 1) Check existing globals
    for name in ("app", "application", "flask_app"):
        if name in globals() and globals()[name] is not None:
            globals()["app"] = globals()[name]
            return

    # 2) Check factory functions
    for factory_name in ("create_app", "make_app", "build_app"):
        factory = globals().get(factory_name)
        if callable(factory):
            try:
                app_instance = factory()
                if app_instance:
                    globals()["app"] = app_instance
                    return
            except Exception:
                continue

    # 3) Probe common modules
    candidate_modules = ("wsgi", "app", "nija_app", "nija_app_main")
    for mod_name in candidate_modules:
        try:
            spec = importlib.util.find_spec(mod_name)
            if not spec:
                continue
            mod = importlib.import_module(mod_name)
            for name in ("app", "application", "create_app"):
                obj = getattr(mod, name, None)
                if obj:
                    if callable(obj) and name.startswith("create"):
                        globals()["app"] = obj()
                    else:
                        globals()["app"] = obj
                    return
        except Exception:
            continue

    # 4) Last resort: tiny health-check Flask app
    fallback = Flask("fallback_app")
    @fallback.route("/__health__")
    def health(): return jsonify({"status": "fallback-ok"}), 200
    globals()["app"] = fallback
    logger.warning("WSGI shim: using fallback Flask health-check app.")

# Run shim automatically
_expose_wsgi_app()
