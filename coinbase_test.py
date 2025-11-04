import os
import time
import base64
import requests
from ecdsa import SigningKey, NIST256p
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("coinbase_test")

# Load your Advanced API credentials from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PASSPHRASE = ""  # leave blank
BASE_URL = "https://api.coinbase.com"

if not API_KEY or not API_SECRET:
    log.error("Missing Coinbase API key or secret")
    raise SystemExit(1)

# Convert single-line PEM into real PEM
API_SECRET_PEM = API_SECRET.replace("\\n", "\n")

# Load signing key
try:
    sk = SigningKey.from_pem(API_SECRET_PEM)
    log.info("ECDSA Private key loaded successfully")
except Exception as e:
    log.exception("Failed to load private key: %s", e)
    raise SystemExit(1)


def sign_request(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    signature = sk.sign(message.encode())
    signature_b64 = base64.b64encode(signature).decode()
    return timestamp, signature_b64


def get_accounts():
    path = "/v2/accounts"
    ts, sig = sign_request("GET", path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.get(BASE_URL + path, headers=headers, timeout=15)
    if resp.status_code != 200:
        log.error("Status=%s Body=%s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    try:
        accounts = get_accounts()
        for acct in accounts.get("data", []):
            if acct["balance"]["currency"] == "USD":
                print("USD Spot Balance:", acct["balance"]["amount"])
    except Exception as e:
        log.exception("Failed to fetch accounts: %s", e)
