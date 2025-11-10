# nija_client.py - root shim to load app client safely
from pathlib import Path
import importlib.util

try:
    # Try normal package import first
    from app.nija_client import CoinbaseClient  # type: ignore
except Exception:
    # Fallback: attempt to load root nija_client.py if exists
    try:
        import nija_client as _mod
        CoinbaseClient = getattr(_mod, "CoinbaseClient")
    except Exception:
        # Last-resort: load app/nija_client.py via file path
        APP_FILE = Path(__file__).resolve().parent / "app" / "nija_client.py"
        if APP_FILE.exists():
            spec = importlib.util.spec_from_file_location("app_nija_client", str(APP_FILE))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)  # type: ignore
            CoinbaseClient = getattr(m, "CoinbaseClient")
        else:
            raise ImportError("Cannot find app/nija_client.py or root nija_client.py")

__all__ = ["CoinbaseClient"]
