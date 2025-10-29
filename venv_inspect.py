# venv_inspect.py
import os
import sys
import re
import pkgutil
import importlib

VENV_SITE = '/opt/render/project/src/.venv/lib/python3.13/site-packages'

print(">>> venv_inspect starting")
print(">>> python executable:", sys.executable)
print(">>> initial sys.path head:", sys.path[:6])
print(">>> expected venv site-packages:", VENV_SITE)
if VENV_SITE not in sys.path:
    sys.path.insert(0, VENV_SITE)
    print(">>> inserted venv site-packages at front of sys.path")

def safe_listdir(path, max_items=50):
    try:
        items = os.listdir(path)
        print(f">>> LIST {path} : {len(items)} entries (showing up to {max_items})")
        print("    sample:", items[:max_items])
    except Exception as e:
        print(f">>> LIST ERROR {path}: {e}")

# 1) Top-level checks
print("\n=== TOP-LEVEL PACKAGE CHECKS ===")
candidates = [
    os.path.join(VENV_SITE, "coinbase_advanced_py"),
    os.path.join(VENV_SITE, "coinbase-advanced-py"),
    os.path.join(VENV_SITE, "coinbase"),
    os.path.join(VENV_SITE, "coinbase_advanced_py-1.8.2.dist-info"),
]
for c in candidates:
    print("\n>>> CHECK PATH:", c)
    if os.path.exists(c):
        safe_listdir(c)
    else:
        print("   (not found)")

# 2) pkgutil / import hints
print("\n=== pkgutil / import hints ===")
try:
    loader = pkgutil.find_loader("coinbase_advanced_py")
    print(">>> pkgutil.find_loader('coinbase_advanced_py') ->", loader)
except Exception as e:
    print(">>> pkgutil.find_loader error:", e)

try:
    import coinbase_advanced_py as capp
    print(">>> imported top-level coinbase_advanced_py:", capp)
    print("    __file__:", getattr(capp, "__file__", None))
    print("    __path__:", getattr(capp, "__path__", None))
    # list first 50 submodules (if any)
    for p in getattr(capp, "__path__", []):
        print("    scanning path:", p)
        try:
            for info in pkgutil.iter_modules([p]):
                print("      submodule:", info.name, "ispkg=", info.ispkg)
        except Exception as e:
            print("      iter_modules error:", e)
except Exception as e:
    print(">>> import coinbase_advanced_py failed:", repr(e))

# 3) Quick attempts to import likely paths
print("\n=== TRY IMPORT LIKELY MODULE PATHS ===")
try_paths = [
    "coinbase_advanced_py.client",
    "coinbase_advanced_py.clients",
    "coinbase_advanced_py.api",
    "coinbase_advanced_py.api.client",
    "coinbase_advanced_py._client",
    "coinbase",
    "coinbase.client",
]
for mod in try_paths:
    try:
        m = importlib.import_module(mod)
        print(f">>> SUCCESS import {mod} -> module {m} (file={getattr(m, '__file__', None)})")
        # list attributes that might indicate clients
        attrs = [a for a in dir(m) if re.search(r"Client|Coinbase|client", a, re.I)]
        print("    candidate attrs:", attrs[:60])
    except Exception as e:
        print(f">>> FAIL import {mod}: {e}")

# 4) Textual search for likely class names within venv site-packages
print("\n=== TEXTUAL SEARCH (class *Client / Coinbase) ===")
def search_text(root, pattern, limit=200):
    found = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # skip very deep scans for brevity
        if dirpath.count(os.sep) - root.count(os.sep) > 6:
            continue
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if re.search(pattern, txt):
                rel = os.path.relpath(p, root)
                print("   match:", rel)
                found += 1
                if found >= limit:
                    print("   (limit reached)")
                    return
    if found == 0:
        print("   (no matches)")

if os.path.exists(VENV_SITE):
    search_text(VENV_SITE, r"class\s+\w*Client\b", limit=200)
    search_text(VENV_SITE, r"\bCoinbaseClient\b", limit=200)
    search_text(VENV_SITE, r"\bCoinbase\b", limit=200)
else:
    print(">>> VENV_SITE does not exist:", VENV_SITE)

print("\n>>> venv_inspect complete")
