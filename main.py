#!/usr/bin/env python3
import os
import time
import requests
import logging
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# =========================
# CONFIG / ENV VARIABLES
# =========================
PRIMARY_ORG = os.environ.get("COINBASE_ORG_ID")
PRIMARY_KID = os.environ.get("COINBASE_API_KEY_ID")
PRIMARY_PEM = os.environ.get("COINBASE_PEM_CONTENT")

FALLBACK_ORG = os.environ.get("COINBASE_FALLBACK_ORG_ID")
FALLBACK_KID = os.environ.get("COINBASE_FALLBACK_API_KEY_ID")
FALLBACK_PEM = os.environ.get("COINBASE_FALLBACK_PEM_CONTENT")

COINBASE_BASE_URL = os.environ.get("COINBASE_BASE_URL", "https://api.coinbase.com")

# =========================
# UTILS
# =========================
def get_outbound_ip():
    try:
        ip = requests.get("https://api.ipify.org").text.strip()
        logging.info(f"⚡ Current outbound IP on this run: {ip} (via ipify)")
        logging.info("--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
        logging.info(ip)
        logging.info("---------------------------------------------------------------")
        return ip
    except Exception as e:
        logging.error(f"Failed to detect outbound IP: {e}")
        return None

def load_pem(pem_str):
    try:
        return serialization.load_pem_private_key(pem_str.encode(), password=None, backend=default_backend())
    except Exception as e:
        logging.error(f"Unable to load PEM file. See https://cryptography.io/en/latest/faq/#why-can-t-i-import-my-pem-file for details. {e}")
        return None

def generate_jwt(org, kid, key, method="GET", request_path="/api/v3/brokerage/organizations/{org}/key_permissions".format(org=PRIMARY_ORG)):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat+120,
        "sub": f"/organizations/{org}/apiKeys/{kid}",
        "request_path": request_path,
        "method": method,
        "jti": f"nija-{iat}"
    }
    headers = {"alg":"ES256","kid":kid,"typ":"JWT"}
    return jwt.encode(payload, key, algorithm="ES256", headers=headers)

def test_key(org, kid, pem):
    key_obj = load_pem(pem)
    if not key_obj:
        return False
    token = generate_jwt(org, kid, key_obj)
    url = f"{COINBASE_BASE_URL}/api/v3/brokerage/organizations/{org}/key_permissions"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            logging.info(f"✅ Key valid: org={org} kid={kid}")
            return True
        else:
            logging.warning(f"❌ [{r.status_code}] Unauthorized for org={org} kid={kid}")
            return False
    except Exception as e:
        logging.error(f"Error testing key org={org} kid={kid}: {e}")
        return False

def print_env_instructions():
    logging.info("--- Railway / Render env export lines (copy & paste) ---")
    logging.info(f"export COINBASE_ORG_ID={PRIMARY_ORG}")
    logging.info(f"export COINBASE_API_KEY_ID={PRIMARY_KID}")
    logging.info(f"export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    if FALLBACK_ORG and FALLBACK_KID:
        logging.info(f"export COINBASE_FALLBACK_ORG_ID={FALLBACK_ORG}")
        logging.info(f"export COINBASE_FALLBACK_API_KEY_ID={FALLBACK_KID}")
        logging.info(f"export COINBASE_FALLBACK_PEM_CONTENT='(optional fallback PEM)'")
    logging.info("------------------------------------------------------")

# =========================
# MAIN
# =========================
def main():
    logging.info("🔥 Nija Trading Bot bootstrap starting...")
    get_outbound_ip()

    # Try primary key
    logging.info(f"Checking primary key: org={PRIMARY_ORG} kid={PRIMARY_KID}")
    if test_key(PRIMARY_ORG, PRIMARY_KID, PRIMARY_PEM):
        logging.info("🎯 Connected with primary key!")
        return

    logging.warning("Primary key failed.")
    # Try fallback key if present
    if FALLBACK_ORG and FALLBACK_KID and FALLBACK_PEM:
        logging.info(f"Checking fallback key: org={FALLBACK_ORG} kid={FALLBACK_KID}")
        if test_key(FALLBACK_ORG, FALLBACK_KID, FALLBACK_PEM):
            logging.info("🎯 Connected with fallback key!")
            return
        else:
            logging.warning("Fallback key failed.")
    else:
        logging.info("No fallback key configured. Add COINBASE_FALLBACK_* env vars for unrestricted key.")

    # If both fail
    logging.error("❌ Coinbase key validation failed. Fix the following:")
    print_env_instructions()

if __name__ == "__main__":
    main()
