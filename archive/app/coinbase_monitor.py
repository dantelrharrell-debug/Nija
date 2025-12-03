# coinbase_monitor.py
import time
import sys
import importlib
import pkgutil
import logging
import os

LOG = logging.getLogger("coinbase_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DEBUG_PATH = "/app/logs/coinbase_module_debug.txt"
PROBE_INTERVAL = int(os.environ.get("COINBASE_PROBE_INTERVAL", "10"))  # seconds

TOP_CANDIDATES = [
    "coinbase_advanced_py",
    "coinbase_advanced",
    "coinbaseadvanced",
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced_py.rest",
    "coinbase_advanced.rest",
]

CLIENT_NAMES = ["Client","RESTClient","APIClient","CoinbaseClient","CoinbaseRESTClient","AdvancedClient"]

def write(path, content):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        LOG.exception("Failed writing debug file")

def probe_once():
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n\n==== probe @ {ts} ====\n"
    write(DEBUG_PATH, header)
    write(DEBUG_PATH, "sys.path:\n")
    for p in sys.path:
        write(DEBUG_PATH, f"  {p}\n")
    write(DEBUG_PATH, "\nInstalled top-level packages (pkgutil.iter_modules):\n")
    try:
        for m in pkgutil.iter_modules():
            write(DEBUG_PATH, f"  {m.name}\n")
    except Exception:
        LOG.exception("pkgutil.iter_modules failed")

    found_any = False
    for name in TOP_CANDIDATES:
        try:
            m = importlib.import_module(name)
            found_any = True
            write(DEBUG_PATH, f"\nImported: {name} -> file={getattr(m,'__file__',None)}\n")
            attrs = sorted([a for a in dir(m) if not a.startswith("__")])
            write(DEBUG_PATH, f"  attributes (sample up to 200): {attrs[:200]}\n")
            # look for client-like objects
            for c in CLIENT_NAMES:
                if hasattr(m, c):
                    write(DEBUG_PATH, f"  FOUND attribute '{c}' in {name}\n")
            # scan attributes heuristically
            for a in attrs:
                if "client" in a.lower() or a.lower().endswith("client"):
                    write(DEBUG_PATH, f"  heuristic attribute: {a}\n")
        except Exception as e:
            write(DEBUG_PATH, f"Could not import {name}: {type(e).__name__}: {e}\n")
    if not found_any:
        write(DEBUG_PATH, "\nNo candidate package imported from TOP_CANDIDATES.\n")
    write(DEBUG_PATH, "==== end probe ====\n")
    return

def main():
    write(DEBUG_PATH, "\n\n=== coinbase_monitor started ===\n")
    # do a few probes, then sleep and probe again forever
    while True:
        try:
            probe_once()
        except Exception:
            LOG.exception("probe failed")
        time.sleep(PROBE_INTERVAL)

if __name__ == "__main__":
    main()
