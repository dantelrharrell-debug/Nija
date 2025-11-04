# nija_client.py
import os, time, base64, logging, requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    log.error("Missing Coinbase credentials.")
    raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

if "\\n" in API_SECRET:
    API_SECRET = API_SECRET.replace("\\n", "\n")

try:
    _PRIVATE_KEY = load_pem_private_key(API_SECRET.encode(), password=None)
except Exception as e:
    log.exception("Failed to load private key: %s", e)
    raise

def _sign(ts: str, method: str, path: str, body: str = "") -> str:
    payload = (ts + method.upper() + path + (body or "")).encode()
    sig_der = _PRIVATE_KEY.sign(payload, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig_der).decode()

def _cdp_request(method: str, path: str, body: str = ""):
    ts = str(int(time.time()))
    sig = _sign(ts, method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = API_BASE.rstrip("/") + path
    resp = requests.request(method, url, headers=headers, data=body, timeout=15)
    log.debug("CDP resp status=%s", resp.status_code)
    return resp

def get_usd_spot_balance():
    """
    Returns float USD balance (0.0 if none). Uses /v2/accounts CDP route.
    """
    resp = _cdp_request("GET", "/v2/accounts")
    try:
        data = resp.json()
    except Exception:
        log.error("CDP accounts not JSON: status=%s body=%s", resp.status_code, resp.text[:2000])
        if resp.status_code == 401:
            raise RuntimeError("Unauthorized from Coinbase Advanced API (401).")
        resp.raise_for_status()
    for acc in data.get("data", []):
        bal = acc.get("balance", {})
        if bal.get("currency") == "USD":
            return float(bal.get("amount", 0))
    return 0.0
