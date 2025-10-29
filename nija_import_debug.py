# nija_import_debug.py
import sys, os, importlib, pkgutil, traceback

VENV_SITE = '/opt/render/project/src/.venv/lib/python3.13/site-packages'
print(">>> sys.path (head):", sys.path[:6])
print(">>> Ensuring venv site-packages exists at:", VENV_SITE)
if VENV_SITE not in sys.path:
    sys.path.insert(0, VENV_SITE)
    print(">>> Inserted venv site-packages at front of sys.path")

def list_dir(path):
    try:
        items = os.listdir(path)
        print(f">>> LIST {path}: {len(items)} entries")
        # print a short sample, but not everything
        print("    sample:", items[:40])
    except Exception as e:
        print(f">>> LIST ERROR {path}: {e}")

# 1) Confirm installed package location
try:
    import pkgutil
    spec = pkgutil.find_loader("coinbase_advanced_py")
    print(">>> pkgutil.find_loader('coinbase_advanced_py') ->", spec)
except Exception as e:
    print(">>> pkgutil.find_loader error:", e)

# 2) Show site-packages coinbase_advanced_py folder contents
possible_pkg_paths = [
    os.path.join(VENV_SITE, "coinbase_advanced_py"),
    os.path.join(VENV_SITE, "coinbase-advanced-py"),
    os.path.join(VENV_SITE, "coinbase_advanced_py-1.8.2.dist-info"),
    os.path.join(VENV_SITE, "coinbase_advanced_py-1.8.2.egg-info"),
]
for p in possible_pkg_paths:
    list_dir(p)

# 3) Try to import the top-level package and list submodules
try:
    import coinbase_advanced_py as capp
    print(">>> Imported coinbase_advanced_py module:", capp)
    print("    __file__:", getattr(capp, "__file__", None))
    print("    __path__:", getattr(capp, "__path__", None))
    # list submodules found by pkgutil.iter_modules on package path(s)
    pkg_paths = getattr(capp, "__path__", [])
    for pkg_path in pkg_paths:
        print(">>> scanning path:", pkg_path)
        try:
            for info in pkgutil.iter_modules([pkg_path]):
                print("   submodule:", info.name, "ispkg=", info.ispkg)
        except Exception as e:
            print("   iter_modules error:", e)
except Exception as e:
    print(">>> import coinbase_advanced_py failed:", repr(e))
    traceback.print_exc()

# 4) Attempt to import likely module paths for CoinbaseClient
candidates = [
    "coinbase_advanced_py.client",
    "coinbase_advanced_py.clients",
    "coinbase_advanced_py.api.client",
    "coinbase.client",
    "coinbase_advanced_py.client.client",
    "coinbase_advanced_py.client_api",
]
for mod in candidates:
    try:
        m = importlib.import_module(mod)
        print(f">>> SUCCESS import {mod} -> module {m}")
        # show attributes that might contain CoinbaseClient
        attrs = [a for a in dir(m) if "Coinbase" in a or "coinbase" in a.lower() or "Client" in a]
        print("    possible attrs:", attrs[:30])
    except Exception as e:
        print(f">>> FAIL import {mod}: {e}")

# 5) Search for 'CoinbaseClient' symbol anywhere under site-packages coinbase_advanced_py dir
def search_for_symbol(root, symbol="CoinbaseClient"):
    print(f">>> Searching for {symbol} under {root}")
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".py"):
                try:
                    p = os.path.join(dirpath, fn)
                    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        txt = fh.read()
                        if symbol in txt:
                            rel = os.path.relpath(p, root)
                            found.append(rel)
                except Exception:
                    pass
    print(f">>> Found {len(found)} files containing {symbol}:")
    for f in found[:50]:
        print("   -", f)
    return found

for root_candidate in [os.path.join(VENV_SITE, "coinbase_advanced_py"), VENV_SITE]:
    if os.path.exists(root_candidate):
        search_for_symbol(root_candidate, "CoinbaseClient")

print(">>> Diagnostic complete.")
