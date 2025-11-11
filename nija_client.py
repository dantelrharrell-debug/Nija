# nija_client.py  (repo root shim - safe)
"""
Shim so code can `from nija_client import CoinbaseClient`.
Prefer implementation at app/nija_client.py.
This shim tries to import app.nija_client first; if that fails it will load the file
directly from disk (without importing the current module name), avoiding circular imports.
"""

try:
    # preferred: package import
    from app.nija_client import CoinbaseClient  # type: ignore
except Exception:
    import importlib.util
    from pathlib import Path
    APP_FILE = Path(__file__).resolve().parent / "app" / "nija_client.py"
    if APP_FILE.exists():
        spec = importlib.util.spec_from_file_location("app_nija_client", str(APP_FILE))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        CoinbaseClient = getattr(module, "CoinbaseClient")
    else:
        # re-raise the original import error so the process fails visibly
        raise
__all__ = ["CoinbaseClient"]
