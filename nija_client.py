# nija_client.py (root shim)
try:
    # prefer package import so user code can do `from app.nija_client import CoinbaseClient`
    from app.nija_client import CoinbaseClient  # type: ignore
except Exception:
    # fallback to local file if present
    from importlib import import_module
    try:
        _mod = import_module("nija_client")  # if root module replaced by older file, this prevents circular import
        CoinbaseClient = getattr(_mod, "CoinbaseClient")
    except Exception:
        # last-resort: load file from app/nija_client.py path
        import importlib.util
        from pathlib import Path
        APP_FILE = Path(__file__).resolve().parent / "app" / "nija_client.py"
        if APP_FILE.exists():
            spec = importlib.util.spec_from_file_location("app_nija_client", str(APP_FILE))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)  # type: ignore
            CoinbaseClient = getattr(m, "CoinbaseClient")
        else:
            raise
__all__ = ["CoinbaseClient"]
