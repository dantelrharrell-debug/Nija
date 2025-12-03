# Save as: try_coinbase_variants.py
import os, time, requests, jwt, itertools
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ----------------------------
# CONFIG (env variables)
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY")           # short id e.g. 9e33...
COINBASE_API_FULL = os.getenv("COINBASE_API_KEY_FULL")       # full path organizations/.../apiKeys/...
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
CB_VERSION = os.getenv("CB_VERSION", "2025-11-16")           # set to today if not set

# Validation
if not COINBASE_ORG_ID:
    raise SystemExit("Set COINBASE_ORG_ID in env.")
if not (COINBASE_API_KEY_ID or COINBASE_API_FULL):
    raise SystemExit("Set COINBASE_API_KEY (short id) or COINBASE_API_KEY_FULL in env.")
if not (COINBASE_PEM_CONTENT or COINBASE_PEM_PATH):
    raise SystemExit("Set COINBASE_PEM_CONTENT (preferred) or COINBASE_PEM_PATH.")

# Load PEM text
def load_pem():
    if COINBASE_PEM_CONTENT:
        s = COINBASE_PEM_CONTENT
        if "\\n" in s:
            s = s.replace("\\n", "\n")
        return s.strip()
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        return f.read().replace("\r","").strip()

pem_text = load_pem()

# Try to load key
try:
    private_key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
    print("✅ PEM loaded OK")
except Exception as e:
    print("❌ Failed to load PEM:", e)
    raise

# Prepare kid and sub candidates
kids = []
subs = []

if COINBASE_API_FULL:
    kids.append(COINBASE_API_FULL)
    # also append short id if full contains it
    subs.append(COINBASE_API_FULL.split("/")[-1])
else:
    # only short id known
    subs.append(COINBASE_API_KEY_ID)

if COINBASE_API_KEY_ID:
    subs.append(COINBASE_API_KEY_ID)
    # if full not provided, add a plausible full kid if org known
    if COINBASE_ORG_ID:
        kids.append(f"organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}")

# de-dupe
kids = list(dict.fromkeys(kids))
subs = list(dict.fromkeys(subs))

print("Candidates kid:", kids)
print("Candidates sub:", subs)
print("CB-VERSION:", CB_VERSION)
print("Container time (UTC):", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
print("Local time:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))

# Target request
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
method = "GET"
url = f"https://api.coinbase.com{path}"

def build_token(sub_value, kid_value, lifetime=120):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + lifetime,
        "sub": sub_value,
        "request_path": path,
        "method": method
    }
    headers = {"alg": "ES256", "kid": kid_value}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token, payload, headers

# Try all combos
results = []
for sub_v, kid_v in itertools.product(subs, kids):
    print("\n--- Trying combo ---")
    print("sub:", sub_v)
    print("kid:", kid_v)
    token, payload, hdrs = build_token(sub_v, kid_v)
    print("JWT header (unverified):", hdrs)
    print("JWT payload (unverified):", payload)
    # short preview
    print("JWT preview (first 64):", token[:64])

    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": CB_VERSION,
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print("HTTP status:", r.status_code)
        print("Response text:", r.text[:1000])
        results.append((sub_v, kid_v, r.status_code, r.text))
        if r.status_code == 200:
            print("✅ SUCCESS with this combo — you're connected.")
            break
    except Exception as e:
        print("Request exception:", e)
        results.append((sub_v, kid_v, "EXC", str(e)))

# Summary
print("\n=== SUMMARY ===")
for sub_v, kid_v, status, text in results:
    print("sub:", sub_v, "kid:", kid_v, "=>", status)
    if status == 401:
        print("  -> 401 Unauthorized. Check permissions, org-match, and clock.")
    if status == "EXC":
        print("  -> Exception:", text[:200])

print("\nNext steps if still 401:")
print(" - Verify on Coinbase UI that the API key (ID 9e33...) is set for the same Organization ID:", COINBASE_ORG_ID)
print(" - Confirm the key has 'view/accounts' permission for brokerage.")
print(" - Confirm the key is an Advanced/Brokerage API key (not an Exchange REST key).")
print(" - Check server/container clock is accurate (ntp).")
print(" - If you want, paste the successful JWT header/payload here (not the full token) and I'll inspect claims.")
