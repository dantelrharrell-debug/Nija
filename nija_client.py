# nija_client.py  (root shim)
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parent
IMPL = ROOT / "app" / "nija_client.py"

if IMPL.exists():
    spec = importlib.util.spec_from_file_location("app_nija_client", str(IMPL))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    CoinbaseClient = getattr(module, "CoinbaseClient")
else:
    raise ImportError(f"Cannot find implementation at {IMPL}. Ensure app/nija_client.py exists and is committed.")

__all__ = ["CoinbaseClient"]
