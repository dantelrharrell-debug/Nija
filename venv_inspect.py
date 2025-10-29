# venv_inspect.py
import os, sys, re

VENV_SITE = '/opt/render/project/src/.venv/lib/python3.13/site-packages'
print(">>> sys.path (head):", sys.path[:6])
print(">>> VENV_SITE exists:", os.path.exists(VENV_SITE))

def list_path(p):
    try:
        for root, dirs, files in os.walk(p):
            # limit output
            if root.count(os.sep) - p.count(os.sep) > 3:
                continue
            print("DIR:", root)
            print("  subdirs:", dirs[:20])
            print("  files sample:", files[:30])
    except Exception as e:
        print("LIST ERROR", e)

# List the top-level package directories relevant to coinbase
candidates = [
    os.path.join(VENV_SITE, "coinbase_advanced_py"),
    os.path.join(VENV_SITE, "coinbase_advanced_py-1.8.2.dist-info"),
    os.path.join(VENV_SITE, "coinbase-advanced-py"),
    os.path.join(VENV_SITE, "coinbase"),
]
for c in candidates:
    print("\n=== LISTING:", c)
    if os.path.exists(c):
        list_path(c)
    else:
        print("  not found")

# Search a bit for likely class names
def search_symbol(root, pattern, limit=200):
    print(f"\nSearching for pattern '{pattern}' under {root}")
    found = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".py"): continue
            p = os.path.join(dirpath, fn)
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except:
                continue
            if re.search(pattern, txt):
                print("  match:", os.path.relpath(p, root))
                found += 1
                if found >= limit:
                    return
    if found == 0:
        print("  no matches found")

if os.path.exists(VENV_SITE):
    # look for class names that could be clients
    search_symbol(VENV_SITE, r"class\s+\w*Client")
    search_symbol(VENV_SITE, r"Coinbase", limit=200)
    search_symbol(VENV_SITE, r"def\s+Client|def\s+create_client", limit=200)
else:
    print("VENV_SITE missing, cannot search")
print("done")
