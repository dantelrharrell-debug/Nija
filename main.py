import os, logging

logging.basicConfig(level=logging.INFO)
PEM = os.getenv("COINBASE_PEM_CONTENT")
API_KEY = os.getenv("COINBASE_API_KEY_ID")
if PEM and API_KEY:
    logging.info("✅ PEM loaded and API key present")
else:
    logging.error("❌ Check PEM formatting and API key")

# normalize common single-line / escaped newline cases into a real file Coinbase client can load
pem_val = PEM or ""
if pem_val:
    # if the env uses literal "\n" sequences, convert them
    if "\\n" in pem_val and "-----BEGIN" in pem_val:
        pem_val = pem_val.replace("\\n", "\n")
    # if the env is base64 (no BEGIN), try to detect — do NOT print the key
    if "-----BEGIN" not in pem_val and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n" for c in pem_val.strip()):
        try:
            import base64
            pem_val = base64.b64decode(pem_val).decode("utf-8")
        except Exception:
            pass
    try:
        with open("/tmp/coinbase_pem_debug.pem", "w") as f:
            f.write(pem_val)
        logging.info("Saved normalized PEM to /tmp/coinbase_pem_debug.pem")
    except Exception as e:
        logging.error(f"Could not write normalized PEM: {e}")

#!/usr/bin/env python3
"""
main.py - Coinbase Advanced diagnostic + auto-fallback validator + minimal debug API

Features:
- Detects outbound IP and prints exact whitelist line for Coinbase Advanced.
- Normalizes PEM (handles escaped \\n or true multiline), saves debug copy to /tmp.
- Loads primary key; generates JWT preview.
- If PERFORM_LIVE_CALL=1, calls /key_permissions; on 401 tries fallback key (if configured).
- On successful validation, fetches accounts and prints them.
- Small Flask app with /debug returning status report.
- Prints Railway/Render env export lines when failing.

Env vars:
- COINBASE_ORG_ID
- COINBASE_API_KEY_ID
- COINBASE_PEM_CONTENT   (preferred multiline PEM; single-line escaped with \\n also supported)
Optional fallback:
- COINBASE_FALLBACK_ORG_ID
- COINBASE_FALLBACK_API_KEY_ID
- COINBASE_FALLBACK_PEM_CONTENT

Optional flags:
- PERFORM_LIVE_CALL=1 (default 0) => actually call Coinbase /key_permissions
- SEND_LIVE_TRADES=1 (default 0) => enable live trades (BE CAREFUL)
"""

import os
import sys
import time
import json
import logging
import datetime
from typing import Optional, Tuple

import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from flask import Flask, jsonify

# --- Logging ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("nija_coinbase")

CB_VERSION = datetime.datetime.utcnow().strftime("%Y-%m-%d")

# --- Env helpers ---
def env(name: str, fallback: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v and v.strip() != "" else fallback

# --- PEM normalization & load ---
def normalize_pem(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = raw.strip()
    # convert escaped newlines to real newlines if needed
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    # Trim extra blank lines and whitespace
    lines = [ln.rstrip() for ln in s.splitlines()]
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")

def save_pem_debug(pem_text: str, path: str = "/tmp/coinbase_pem_debug.pem"):
    try:
        with open(path, "w") as f:
            f.write(pem_text)
        log.info("Saved normalized PEM to %s", path)
    except Exception as e:
        log.error("Failed to save PEM debug file: %s", e)

def load_private_key(pem_text: str):
    try:
        return serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
    except Exception as e:
        return e  # return exception for diagnostics

# --- Outbound IP detection ---
def get_outbound_ip() -> Tuple[Optional[str], Optional[str]]:
    services = [
        ("https://api.ipify.org?format=json", "ipify"),
        ("https://ifconfig.co/json", "ifconfig.co"),
        ("https://ifconfig.me/all.json", "ifconfig.me")
    ]
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
    return None, None

# --- JWT preview and Coinbase calls ---
def make_jwt_token(key_obj, kid: str, org_id: str, api_key_id: str, path: str, method: str = "GET"):
    iat = int(time.time())
    sub = f"/organizations/{org_id}/apiKeys/{api_key_id}"
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": sub,
        "request_path": path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    try:
        token = jwt.encode(payload, key_obj, algorithm="ES256", headers=headers)
        return token, payload, headers, None
    except Exception as e:
        return None, payload, headers, str(e)

def call_key_permissions(token: str, org_id: str):
    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    url = "https://api.coinbase.com" + path
    try:
        r = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": CB_VERSION,
            "Content-Type": "application/json"
        }, timeout=10)
        return r.status_code, r.text, r
    except Exception as e:
        return None, str(e), None

def fetch_accounts(token: str, org_id: str):
    path = f"/api/v3/brokerage/organizations/{org_id}/accounts"
    url = "https://api.coinbase.com" + path
    try:
        r = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": CB_VERSION,
            "Content-Type": "application/json"
        }, timeout=10)
        return r.status_code, r.text, r
    except Exception as e:
        return None, str(e), None

# --- Diagnostic/validation flow ---
def validate_key(org_id: str, api_key_id: str, pem_raw: str, perform_live: bool = False):
    report = {"org": org_id, "kid": api_key_id}
    if not org_id or not api_key_id or not pem_raw:
        report["error"] = "Missing env values (ORG/KID/PEM)."
        return False, report

    pem = normalize_pem(pem_raw)
    save_pem_debug(pem)
    key_obj = load_private_key(pem)
    if isinstance(key_obj, Exception):
        report["error"] = f"Unable to parse PEM: {key_obj}"
        return False, report

    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    token, payload, headers, err = make_jwt_token(key_obj, api_key_id, org_id, api_key_id, path)
    if err:
        report["error"] = f"JWT generation error: {err}"
        return False, report

    report["jwt_preview"] = str(token)[:200]
    report["jwt_payload_unverified"] = payload
    report["jwt_header_unverified"] = headers

    if perform_live:
        status, text, raw = call_key_permissions(token, org_id)
        report["http_status"] = status
        report["body_text"] = text
        if status == 200:
            # success
            return True, report
        elif status == 401:
            return False, report
        else:
            return False, report
    else:
        # not performing live call; return token preview as success indicator
        return True, report

# --- Print copy-paste env lines ---
def print_export_lines(org_id, kid, pem_text):
    print("\n--- Railway / Render env export lines (copy & paste) ---")
    print(f"export COINBASE_ORG_ID={org_id}")
    print(f"export COINBASE_API_KEY_ID={kid}")
    print("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    if pem_text:
        print("\nExample PEM (multiline) to paste into COINBASE_PEM_CONTENT:")
        print(pem_text)
        print("\nIf your PaaS requires single-line escaped env, use:")
        print("export COINBASE_PEM_CONTENT='{}'".format(pem_text.replace("\n", "\\n")))
    print("------------------------------------------------------\n")

# --- Main startup logic ---
def bootstrap_and_run():
    log.info("🔥 Nija Trading Bot bootstrap starting...")

    # detect outbound IP
    ip, src = get_outbound_ip()
    if ip:
        log.info("⚡ Current outbound IP on this run: %s (via %s)", ip, src or "ip-service")
        print("\n--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
        print(ip)
        print("---------------------------------------------------------------\n")
    else:
        log.warning("Could not detect outbound IP. Check PaaS dashboard for egress IP.")

    # Primary envs
    ORG = env("COINBASE_ORG_ID")
    KID = env("COINBASE_API_KEY_ID")
    PEM = env("COINBASE_PEM_CONTENT") or env("COINBASE_API_SECRET")  # sometimes used
    # Fallback envs (optional)
    F_ORG = env("COINBASE_FALLBACK_ORG_ID")
    F_KID = env("COINBASE_FALLBACK_API_KEY_ID")
    F_PEM = env("COINBASE_FALLBACK_PEM_CONTENT")

    # perform live if flag set
    PERFORM_LIVE = os.getenv("PERFORM_LIVE_CALL", "0") == "1"

    # Validate primary (JWT preview + optional live call)
    ok, primary_report = validate_key(ORG, KID, PEM or "", perform_live=PERFORM_LIVE)
    if ok and PERFORM_LIVE:
        log.info("✅ Primary key validated with live call.")
        # If validated, fetch accounts for convenience
        # regenerate token with private key to fetch accounts (validate_key returned jwt preview only)
        pem_norm = normalize_pem(PEM)
        key_obj = load_private_key(pem_norm)
        token, *_ = make_jwt_token(key_obj, KID, ORG, KID, f"/api/v3/brokerage/organizations/{ORG}/accounts")
        s, t, raw = fetch_accounts(token, ORG)
        if s == 200:
            log.info("Fetched accounts successfully.")
            try:
                j = raw.json()
                log.info(json.dumps(j, indent=2))
            except Exception:
                log.info("Accounts response: %s", t)
        else:
            log.warning("Could not fetch accounts (HTTP %s): %s", s, t)
        # start app below
    elif ok and not PERFORM_LIVE:
        log.info("✅ Primary key PEM parsed and JWT preview generated. Enable PERFORM_LIVE_CALL=1 to validate against Coinbase.")
    else:
        log.warning("Primary key validation failed: %s", primary_report.get("error", primary_report))
        # Try fallback automatically if provided
        if F_ORG and F_KID and F_PEM:
            log.info("Trying fallback key: org=%s kid=%s", F_ORG, F_KID)
            okf, fall_report = validate_key(F_ORG, F_KID, F_PEM, perform_live=PERFORM_LIVE)
            if okf and PERFORM_LIVE:
                log.info("✅ Fallback key validated with live call.")
                # fetch accounts with fallback token if necessary
            elif okf and not PERFORM_LIVE:
                log.info("✅ Fallback key PEM parsed and JWT preview generated. Enable PERFORM_LIVE_CALL=1 to validate.")
            else:
                log.error("Fallback key validation failed: %s", fall_report.get("error", fall_report))
                print_export_lines(ORG or "<ORG_ID>", KID or "<KID>", normalize_pem(PEM or ""))
                return False
        else:
            log.error("No fallback key configured. Either whitelist the printed IP in Coinbase Advanced for the PRIMARY key, or create a new Advanced key with NO IP restrictions and set it as a fallback.")
            print_export_lines(ORG or "<ORG_ID>", KID or "<KID>", normalize_pem(PEM or ""))
            return False

    return True

# --- Flask debug API (returns latest quick status) ---
app = Flask(__name__)

@app.route("/debug")
def debug_route():
    # Basic info - dynamic run-time; does not include private key material
    ip, src = get_outbound_ip()
    return jsonify({
        "status": "ok",
        "outbound_ip": ip,
        "perform_live_call": os.getenv("PERFORM_LIVE_CALL", "0"),
        "send_live_trades": os.getenv("SEND_LIVE_TRADES", "0"),
        "time": datetime.datetime.utcnow().isoformat() + "Z"
    })

# --- Entrypoint ---
if __name__ == "__main__":
    try:
        ready = bootstrap_and_run()
        if not ready:
            log.error("❌ Bootstrap failed (see logs). Exiting with code 1.")
            # exit non-zero to show failure in PaaS
            sys.exit(1)
        # If bootstrap successful, start debug Flask server for convenience
        host = "0.0.0.0"
        port = int(os.getenv("PORT", "5000"))
        log.info("✅ Bootstrap succeeded. Starting debug server on %s:%s", host, port)
        app.run(host=host, port=port)
    except Exception as e:
        log.exception("Unhandled exception during startup: %s", e)
        sys.exit(1)
