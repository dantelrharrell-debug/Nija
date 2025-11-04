# cdp_test_accounts.py
import os, time, base64, logging, requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cdp_test")

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    log.error("Missing COINBASE_API_KEY or COINBASE_API_SECRET")
    raise SystemExit(1)

# If secret contains literal "\n", convert to real newlines
if "\\n" in API_SECRET:
    API_SECRET = API_SECRET.replace("\\n", "\n")

try:
    private_key = load_pem_private_key(API_SECRET.encode(), password=None)
except Exception as e:
    log.exception("Failed to load PEM private key: %s", e)
    raise SystemExit(1)

def sign_payload(ts: str, method: str, path: str, body: str):
    payload = (ts + method.upper() + path + (body or "")).encode()
    sig_der = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig_der).decode()

def cdp_request(method: str, path: str, body_str: str = ""):
    ts = str(int(time.time()))
    sig = sign_payload(ts, method, path, body_str)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = API_BASE.rstrip("/") + path
    resp = requests.request(method, url, headers=headers, data=body_str, timeout=15)
    log.info("status=%s", resp.status_code)
    snippet = (resp.text or "")[:2000]
    log.info("body_snippet=%s", snippet)
    return resp

if __name__ == "__main__":
    # fetch accounts (v2). For Advanced trading endpoints you may use /v3/...
    r = cdp_request("GET", "/v2/accounts")
    try:
        print(r.json())
    except Exception:
        print("RAW TEXT:", r.text)
        r.raise_for_status()
