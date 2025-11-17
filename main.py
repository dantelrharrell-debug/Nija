# main.py
"""
Nija Trading Bot connection + auto-fallback script for Coinbase Advanced (CDP).
Paste this into your project root as main.py and set env vars in Railway/Render.
"""

import os, time, json, logging, requests, jwt
from typing import Optional, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ---- CONFIG ----
LOG_FILE = os.getenv("NIJA_LOG_FILE", "nija_trading.log")
CB_BASE = "https://api.coinbase.com"
CB_VERSION = time.strftime("%Y-%m-%d")
RETRY_COUNT = int(os.getenv("NIJA_RETRY_COUNT", "3"))
RETRY_DELAY = float(os.getenv("NIJA_RETRY_DELAY", "1"))
ALLOW_UNSAFE_LIVE = os.getenv("ALLOW_UNSAFE_LIVE", "0") == "1"  # MUST be set to 1 to enable live trading

# ---- Logging ----
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger("").addHandler(console)

# ---- Helpers ----
def env(name: str) -> Optional[str]:
    v = os.getenv(name)
    return v if v and v.strip() != "" else None

def normalize_pem(raw: str) -> str:
    if not raw:
        return ""
    pem = raw.strip()
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    lines = [line.strip() for line in pem.splitlines() if line.strip() != ""]
    if not lines:
        return ""
    return "\n".join(lines) + ("\n" if not lines[-1].endswith("\n") else "")

def load_private_key(pem_text: str):
    try:
        return serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
    except Exception as e:
        logging.error("Failed to parse PEM: %s", e)
        return None

def get_outbound_ip() -> Optional[Tuple[str,str]]:
    services = [("https://api.ipify.org?format=json","ipify"), ("https://ifconfig.co/json","ifconfig.co")]
    for url, name in services:
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                try:
                    j = r.json()
                    ip = j.get("ip") or j.get("ip_addr") or j.get("IP")
                    if ip:
                        return ip, name
                except Exception:
                    txt = r.text.strip()
                    if txt:
                        return txt, name
        except Exception:
            continue
    return None

def make_sub(org_id: str, key_id: str) -> str:
    return f"/organizations/{org_id}/apiKeys/{key_id}"

def generate_jwt(private_key_obj, kid: str, sub: str, path: str, method: str="GET") -> Optional[str]:
    try:
        iat = int(time.time())
        payload = {"iat": iat, "exp": iat + 120, "sub": sub, "request_path": path, "method": method.upper(), "jti": f"nija-{iat}"}
        headers = {"alg":"ES256","kid":kid,"typ":"JWT"}
        token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers=headers)
        if isinstance(token, bytes):
            token = token.decode()
        logging.debug("JWT generated: %s", payload)
        return token
    except Exception as e:
        logging.exception("Failed to generate JWT: %s", e)
        return None

def call_key_permissions(token: str, org_id: str):
    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    url = CB_BASE + path
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": CB_VERSION, "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as e:
        return None, str(e)

def try_key(org_id: str, key_id: str, pem_raw: str):
    debug = {"org_id": org_id, "key_id": key_id}
    if not org_id or not key_id or not pem_raw:
        debug["error"] = "missing env for org/key/pem"
        logging.warning("Missing env for key: %s", debug)
        return False, None, debug

    pem = normalize_pem(pem_raw)
    key_obj = load_private_key(pem)
    if not key_obj:
        debug["error"] = "failed to load pem"
        return False, None, debug

    sub = make_sub(org_id, key_id)
    request_path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    token = generate_jwt(key_obj, key_id, sub, request_path, method="GET")
    if not token:
        debug["error"] = "jwt_generation_failed"
        return False, None, debug

    for attempt in range(1, RETRY_COUNT + 1):
        status, body = call_key_permissions(token, org_id)
        logging.info("[Attempt %d] /key_permissions -> %s", attempt, status)
        if status == 200:
            logging.info("✅ Key validated for org=%s kid=%s", org_id, key_id)
            return True, body, {"status": status}
        if status == 401:
            logging.warning("❌ 401 Unauthorized for org=%s kid=%s", org_id, key_id)
            return False, None, {"status": status, "body": body}
        time.sleep(RETRY_DELAY)
    return False, None, {"status": status, "body": body}

def print_railway_env_lines(org, kid, pem):
    print("\n--- Railway / Render env export lines (copy & paste) ---")
    print(f"export COINBASE_ORG_ID={org}")
    print(f"export COINBASE_API_KEY_ID={kid}")
    print("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    escaped = (pem or "").replace("\n", "\\n")
    print(f"export COINBASE_PEM_CONTENT='{escaped}'")
    print("------------------------------------------------------\n")

def print_whitelist_line(ip: str):
    if ip:
        print("\n--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
        print(ip)
        print("----------------------------------------------------------------\n")

# ---- Trading start placeholder (only runs if ALLOW_UNSAFE_LIVE=1) ----
def start_trading():
    logging.info("🚀 start_trading() called.")
    if not ALLOW_UNSAFE_LIVE:
        logging.warning("Live trading disabled (ALLOW_UNSAFE_LIVE != 1). Set env to enable.")
        return
    try:
        # Replace with your live trading module / entrypoint
        from bot_live import execute_trades
        execute_trades()
    except Exception as e:
        logging.error("Error in live trading: %s", e)

def main():
    logging.info("🔥 Nija Trading Bot bootstrap starting...")

    PRIMARY_ORG = env("COINBASE_ORG_ID")
    PRIMARY_KID = env("COINBASE_API_KEY_ID")
    PRIMARY_PEM = env("COINBASE_PEM_CONTENT")

    FALLBACK_ORG = env("COINBASE_FALLBACK_ORG_ID")
    FALLBACK_KID = env("COINBASE_FALLBACK_API_KEY_ID")
    FALLBACK_PEM = env("COINBASE_FALLBACK_PEM_CONTENT")

    outbound = get_outbound_ip()
    if outbound:
        ip, src = outbound
        logging.info("⚡ Current outbound IP on this run: %s (via %s)", ip, src)
        print_whitelist_line(ip)
    else:
        logging.warning("Could not detect outbound IP. If Coinbase returns 401, find egress IP via PaaS dashboard or run 'curl https://api.ipify.org' from host.")

    if not (PRIMARY_ORG and PRIMARY_KID and PRIMARY_PEM):
        logging.error("Primary key envs missing. Please set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT.")
        print_railway_env_lines(PRIMARY_ORG or "<ORG>", PRIMARY_KID or "<KID>", PRIMARY_PEM or "")
        return

    logging.info("Checking primary key: org=%s kid=%s", PRIMARY_ORG, PRIMARY_KID)
    ok, data, dbg = try_key(PRIMARY_ORG, PRIMARY_KID, PRIMARY_PEM)
    if ok:
        print("\nPrimary key validated. Bot is connected to Coinbase Advanced.\n")
        start_trading()
        return

    logging.warning("Primary validation failed: %s", dbg)
    if FALLBACK_ORG and FALLBACK_KID and FALLBACK_PEM:
        logging.info("Trying fallback key: org=%s kid=%s", FALLBACK_ORG, FALLBACK_KID)
        ok2, data2, dbg2 = try_key(FALLBACK_ORG, FALLBACK_KID, FALLBACK_PEM)
        if ok2:
            print("\nFallback key validated. Bot connected using fallback key.\n")
            start_trading()
            return
        logging.error("Fallback failed: %s", dbg2)
    else:
        logging.info("No fallback configured. Add COINBASE_FALLBACK_* env vars for an unrestricted key.")

    logging.error("❌ Coinbase key validation failed. Fix the items below and restart.")
    if outbound:
        print("1) Whitelist this outbound IP in Coinbase Advanced (edit the API key and add):")
        print(f"   {outbound[0]}\n")
    print("2) Or create a new Coinbase Advanced API key with NO IP restrictions, copy its ORG/KID/PEM into your env as fallback.")
    print_railway_env_lines(FALLBACK_ORG or PRIMARY_ORG, FALLBACK_KID or PRIMARY_KID, FALLBACK_PEM or PRIMARY_PEM)
    print("3) Confirm COINBASE_ORG_ID matches the organization that owns the API key.")
    print("4) Restart container after changes.\n")

if __name__ == "__main__":
    main()
