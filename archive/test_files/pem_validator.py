# Save as: pem_validator.py
import os
import re
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

def read_source():
    if COINBASE_PEM_CONTENT:
        s = COINBASE_PEM_CONTENT
        if "\\n" in s:
            s = s.replace("\\n", "\n")
        return s
    if COINBASE_PEM_PATH:
        if not os.path.exists(COINBASE_PEM_PATH):
            print("PEM path missing:", COINBASE_PEM_PATH)
            sys.exit(2)
        with open(COINBASE_PEM_PATH, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    print("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")
    sys.exit(1)

s = read_source()
print("\n--- First 200 characters of source (escaped newlines) ---")
print(s[:200].replace("\n","\\n"))

m = re.search(r"(-----BEGIN [^-]+-----.*?-----END [^-]+-----)", s, flags=re.S)
if not m:
    print("\n❌ NO PEM BLOCK FOUND in provided content/file. File might be JSON/HTML or has extra wrapping.")
    print("\nFIRST 400 CHARS:\n" + s[:400])
    sys.exit(3)

pem = m.group(1).strip()
out_path = "/tmp/fixed_coinbase.pem"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(pem + "\n")
print("\n✅ Extracted PEM written to:", out_path)
print("\nTrying to load the extracted PEM...")

try:
    serialization.load_pem_private_key(pem.encode("utf-8"), password=None, backend=default_backend())
    print("✅ SUCCESS: extracted PEM loads cleanly with cryptography.")
    sys.exit(0)
except Exception as e:
    print("❌ FAILED TO LOAD EXTRACTED PEM:", e)
    sys.exit(4)
