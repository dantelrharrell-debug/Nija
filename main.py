# Replace your existing get_coinbase_client with this diagnostic, flexible factory
import logging
import importlib
import importlib.util
import traceback
import sys
import subprocess
from types import ModuleType

# Python 3.8+ metadata API (fallback to pkg_resources if not available)
try:
    from importlib import metadata as importlib_metadata
except Exception:
    import importlib_metadata

logger = logging.getLogger(__name__)

def _safe_pip_freeze():
    """Return pip freeze as text (non-fatal if pip not available)."""
    try:
        import pip
        # Use pip API may be brittle; fallback to subprocess
        out = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], stderr=subprocess.STDOUT, timeout=30)
        return out.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("pip freeze failed: %s", e)
        return None

def _installed_coinbase_packages():
    """Return installed distributions whose name contains 'coinbase' (case-insensitive)."""
    found = []
    try:
        for dist in importlib_metadata.distributions():
            name = getattr(dist, "metadata", None) and dist.metadata.get("Name") or getattr(dist, "name", None)
            if name and "coinbase" in name.lower():
                try:
                    ver = dist.version
                except Exception:
                    ver = "unknown"
                found.append((name, ver))
    except Exception as e:
        logger.debug("importlib.metadata.distributions() failed: %s", e)
        # fallback: try pkg_resources
        try:
            import pkg_resources
            for dist in pkg_resources.working_set:
                if "coinbase" in dist.project_name.lower():
                    found.append((dist.project_name, dist.version))
        except Exception:
            logger.debug("pkg_resources fallback also failed")
    return found

def _try_import(module_name: str):
    """Attempt to import a module and return (module, exception_obj_or_None)."""
    try:
        mod = importlib.import_module(module_name)
        return mod, None
    except Exception as e:
        return None, e

def _find_spec(name: str):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

def get_coinbase_client(*args, **kwargs):
    """
    Robust factory that:
      - logs installed coinbase-related packages
      - logs pip freeze (if available)
      - tries many import candidates and member names
      - attempts flexible instantiation patterns
      - returns an instance if possible, otherwise falls back to MockClient
    """
    logger.info("=== Coinbase SDK diagnostic start ===")
    try:
        pkg_list = _installed_coinbase_packages()
        logger.info("Installed coinbase-related distributions: %s", pkg_list)
    except Exception as e:
        logger.exception("Failed to list installed distributions: %s", e)

    pip_freeze = _safe_pip_freeze()
    if pip_freeze:
        # keep this line short in logs: only show top lines, full dump is available in debug
        top = "\n".join(pip_freeze.splitlines()[:200])
        logger.info("pip freeze (truncated first 200 lines):\n%s", top)
    else:
        logger.info("pip freeze not available or failed.")

    # Candidate module names and member names to try
    candidates = [
        ("coinbase_advanced_py", None),
        ("coinbase_advanced", None),
        ("coinbase_advanced.client", None),
        ("coinbase_advanced_py.client", None),
        ("coinbase_advanced_py.client.client", None),
        ("coinbase", None),
        ("coinbase.client", None),
        ("coinbase_advanced_py.client.client.Client", None),
        ("coinbase_advanced_py.client.Client", None),
        ("coinbase_advanced_py.Client", None),
        ("coinbase_advanced.Client", None),
        ("coinbase_advanced_py.client.AdvancedClient", None),
        ("coinbase_advanced_py.advanced", None),
        # some packages expose a top-level module with different name:
        ("coinbase_legacy", None),
        ("coinbase_pro", None),
    ]

    tried = []
    for mod_name, _ in candidates:
        # Check spec quickly
        is_spec = _find_spec(mod_name)
        logger.debug("find_spec(%s) -> %s", mod_name, is_spec)
        mod, err = _try_import(mod_name)
        tried.append((mod_name, bool(mod), repr(err) if err else None))
        if mod:
            logger.info("Successfully imported module: %s (type=%s)", mod_name, type(mod))
            # attempt to discover common client entrypoints within module
            for attr in ["Client", "AdvancedClient", "client", "create_client", "CoinbaseClient", "CoinbaseAdvancedClient"]:
                client_obj = getattr(mod, attr, None)
                if client_obj:
                    logger.info("Found attribute %s on module %s (callable=%s)", attr, mod_name, callable(client_obj))
                    try:
                        # If it's a class or factory function, try to instantiate with common patterns
                        if callable(client_obj):
                            # attempt simple call
                            try:
                                instance = client_obj(*args, **kwargs)
                                logger.info("Instantiated client via %s.%s()", mod_name, attr)
                                return instance
                            except TypeError as te:
                                logger.debug("Instantiation TypeError for %s.%s(): %s", mod_name, attr, te)
                                # try instantiating without kwargs
                                try:
                                    instance = client_obj(*args)
                                    logger.info("Instantiated client via %s.%s(*args)", mod_name, attr)
                                    return instance
                                except Exception:
                                    logger.debug("Instantiation without kwargs failed for %s.%s()", mod_name, attr)
                            except Exception as e:
                                logger.exception("Exception while instantiating %s.%s(): %s", mod_name, attr, e)
                                # continue to next attr
                        else:
                            # attribute is not callable: return the attribute (module object) as a fallback
                            logger.info("%s.%s present but not callable; returning attribute as client object", mod_name, attr)
                            return client_obj
                    except Exception as e:
                        logger.exception("Unhandled exception while handling attribute %s on module %s: %s", attr, mod_name, e)
            # No recognized attribute returned an instance: return the module for caller to inspect
            logger.info("Module %s imported but no standard client attr returned an instance. Returning module for manual handling.", mod_name)
            return mod

    # If we get here, no candidate module imported successfully — log the attempts
    logger.warning("No Coinbase SDK module imported successfully. Detailed attempts: %s", tried)
    # Also log full traceback for extra context (this will be an empty traceback here but kept for uniformity)
    logger.warning("Full diagnostic traceback (if any):\n%s", traceback.format_exc())

    # Provide a robust MockClient fallback with helpful stubs
    class MockClient:
        def __init__(self, *a, **k):
            logger.warning("Using MockClient for Coinbase — real SDK not available.")
        def list_accounts(self):
            logger.debug("MockClient.list_accounts called")
            return []
        def get_accounts(self):
            logger.debug("MockClient.get_accounts called")
            return []
        def accounts(self):
            logger.debug("MockClient.accounts called")
            return []
        def close(self):
            logger.debug("MockClient.close called")
            return None

    return MockClient()

# --- BEGIN: WSGI entrypoint compatibility shim ---
# Safe auto-detection/exposure of WSGI `app` callable for gunicorn.
# Paste this at the very end of your main.py to ensure gunicorn can find `app`.
import logging
logger = logging.getLogger(__name__)

def _expose_wsgi_app():
    """
    Attempt to expose a top-level `app` object for gunicorn by:
      1) Using existing `app` / `application` / `flask_app` if present
      2) Calling create_app() / make_app() if defined
      3) Falling back to a minimal Flask health app (logs a warning)
    """
    # Avoid circular imports if Flask isn't installed
    try:
        from flask import Flask, jsonify
    except Exception as e:
        logger.debug("Flask not importable when trying to expose WSGI app: %s", e)
        return

    # 1) Already present
    module_globals = globals()
    for name in ("app", "application", "flask_app", "application_instance"):
        if name in module_globals and module_globals[name] is not None:
            logger.info("WSGI shim: using existing top-level '%s' as app callable.", name)
            # ensure canonical name 'app' is available
            module_globals["app"] = module_globals[name]
            return

    # 2) Factory functions
    for factory_name in ("create_app", "make_app", "build_app", "init_app"):
        factory = module_globals.get(factory_name)
        if callable(factory):
            try:
                logger.info("WSGI shim: calling factory '%s' to create app.", factory_name)
                created = factory()
                if created is not None:
                    module_globals["app"] = created
                    return
            except Exception as e:
                logger.exception("WSGI shim: calling factory %s raised exception: %s", factory_name, e)

    # 3) Try to import common submodules that may hold the app (non-intrusive)
    # e.g., wsgi.py, app.py, nija_app.py, wsgi_app variable names
    candidate_modules = ("wsgi", "app", "nija_app", "nija_app_main", "main_app")
    import importlib, importlib.util
    for m in candidate_modules:
        try:
            spec = importlib.util.find_spec(m)
            if spec:
                mod = importlib.import_module(m)
                for name in ("app", "application", "create_app"):
                    obj = getattr(mod, name, None)
                    if obj:
                        logger.info("WSGI shim: discovered %s.%s", m, name)
                        if callable(obj) and name.startswith("create"):
                            try:
                                module_globals["app"] = obj()
                                return
                            except Exception as e:
                                logger.debug("WSGI shim: factory in module %s failed: %s", m, e)
                        else:
                            module_globals["app"] = obj
                            return
        except Exception:
            logger.debug("WSGI shim: module probe failed for %s", m)

    # 4) Final fallback: create a tiny health-check Flask app so the process doesn't crash
    logger.warning(
        "WSGI shim: No WSGI 'app' callable found in main module. "
        "Creating fallback health-check Flask app to keep process alive. "
        "This is temporary — please expose your real Flask app as `app` or provide a factory `create_app()`."
    )
    fallback = Flask("fallback_app")

    @fallback.route("/__health__", methods=["GET"])
    def _health():
        return jsonify({"status": "fallback-ok", "info": "No real WSGI app found; fallback active"}), 200

    # expose as 'app'
    module_globals["app"] = fallback

# Run shim on import
try:
    _expose_wsgi_app()
except Exception as e:
    # Very defensive: if shim raises, log and continue (avoid masking real errors)
    try:
        logging.exception("Unexpected error while running WSGI shim: %s", e)
    except Exception:
        pass
# --- END: WSGI entrypoint compatibility shim ---
