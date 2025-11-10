# repo-root/nija_client.py - shim to re-export the app implementation
try:
    # prefer package import when app/ is a package
    from app.nija_client import CoinbaseClient  # type: ignore
except Exception:
    # fallback: try loading app/nija_client.py by path (if you don't have a package)
    import importlib.util
    from pathlib import Path
    APP_FILE = Path(__file__).resolve().parent / "app" / "nija_client.py"
    if APP_FILE.exists():
        spec = importlib.util.spec_from_file_location("app_nija_client", str(APP_FILE))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)  # type: ignore
        CoinbaseClient = getattr(m, "CoinbaseClient")
    else:
        raise ImportError("Cannot find app/nija_client.py or root nija_client.py")

__all__ = ["CoinbaseClient"]
