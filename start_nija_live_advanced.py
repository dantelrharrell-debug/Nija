#!/usr/bin/env python3
"""
start_nija_live_advanced.py
Safe, robust Coinbase Advanced (JWT) account fetch + starter loop.
Uses coinbase-advanced-py jwt_generator to build valid JWTs for REST endpoints.
"""

import os
import time
import logging
import requests
from loguru import logger
from dotenv import load_dotenv

# load .env for local dev (safe no-op in prod)
load_dotenv()

# Use the coinbase advanced SDK helper to build JWTs (preferred)
try:
    from coinbase import jwt_generator
except Exception as e:
    logger.error("coinbase-advanced-py not installed or import failed. Install: pip install coinbase-advanced-py")
    raise

# ---------- CONFIG ----------
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
KEY_ID = os.getenv("COINBASE_KEY_ID")  # e.g. organizations/<org_id>/apiKeys/<key_id>
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # full PEM text OR set COINBASE_PRIVATE_KEY_PATH below
PEM_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH")  # if you prefer a file
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# endpoint we want for accounts (Advanced Trade REST)
ACCOUNTS_PATH = "/api/v3/brokerage/accounts"  # official v3 brokerage accounts endpoint

# ---------- Basic Validation ----------
if not (KEY_ID and (PEM_CONTENT or PEM_PATH)):
    logger.error("Missing Coinbase Advanced credentials. Set COINBASE_KEY_ID and COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH.")
    raise SystemExit(1)

if PEM_PATH and not PEM_CONTENT:
    # read file content (safer to mount file into container than put PEM into env)
    try:
        with open(PEM_PATH, "r", encoding="utf-8") as fh:
            PEM_CONTENT = fh.read()
    except Exception as e:
        logger.exception("Cannot read PEM file from COINBASE_PRIVATE_KEY_PATH")
        raise SystemExit(1)

# ---------- Helpers ----------
def build_rest_jwt(method: str, path: str) -> str:
    """
    Build a short-lived REST JWT for the given method+path using SDK helper.
    Uses coinbase.jwt_generator.format_jwt_uri + build_rest_jwt.
    """
    # format uri as docs expect: e.g. "GET api.coinbase.com/api/v3/brokerage/accounts"
    uri = jwt_generator.format_jwt_uri(method.upper(), path)
    # build_rest_jwt expects (uri, key_var, secret_var) where secret_var can be PEM content
    token = jwt_generator.build_rest_jwt(uri, KEY_ID, PEM_CONTENT)
    return token

def safe_request(method: str, path: str, params=None, json_body=None):
    """
    Make authenticated request using JWT; robust handling for JSON decode errors and non-200 status.
    Returns (status_code, parsed_json_or_text)
    """
    try:
        jwt = build_rest_jwt(method, path)
    except Exception as e:
        logger.exception("Failed to build JWT")
        return None, f"jwt_error: {e}"

    url = API_BASE.rstrip("/") + path
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/json",
    }

    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        else:
            resp = requests.request(method.upper(), url, headers=headers, json=json_body, timeout=REQUEST_TIMEOUT)

    except requests.RequestException as e:
        logger.warning(f"HTTP request failed: {e}")
        return None, str(e)

    # handle HTTP status
    status = resp.status_code
    text = resp.text

    # Try parse JSON safely
    try:
        data = resp.json()
        return status, data
    except ValueError:
        # JSON decode error -> log body safely and return text (prevents crashing)
        logger.warning(f"⚠️ JSON decode failed. Status: {status}, Body (first 400 chars): {text[:400]!r}")
        return status, text

# ---------- Fetch accounts (with retries) ----------
def fetch_accounts_with_retry():
    attempts = 0
    while attempts < MAX_RETRIES:
        status, data = safe_request("GET", ACCOUNTS_PATH)
        if status == 200:
            # expect top-level { "data": [ ... ] }
            if isinstance(data, dict) and data.get("data") is not None:
                return data.get("data")
            else:
                logger.warning("Accounts endpoint returned 200 but unexpected body shape.")
                return []
        else:
            logger.warning(f"❌ Failed to fetch accounts. Status: {status}. Retrying in {RETRY_DELAY}s (attempt {attempts+1}/{MAX_RETRIES})")
            attempts += 1
            time.sleep(RETRY_DELAY)

    # all retries failed
    logger.error("❌ No HMAC/Advanced accounts found after retries.")
    return []

# ---------- Main ----------
def main():
    logger.info("Starting Coinbase Advanced account check (safe mode).")
    accounts = fetch_accounts_with_retry()
    if not accounts:
        logger.error("No accounts returned. Aborting bot startup. Check key permissions, org, and PEM.")
        return

    logger.success(f"✅ Fetched {len(accounts)} accounts.")
    for a in accounts:
        # defend against missing fields
        name = a.get("name") or a.get("id") or "unknown"
        currency = a.get("currency") or a.get("currency_code") or "?"
        balance = None
        if isinstance(a.get("balance"), dict):
            balance = a["balance"].get("available") or a["balance"].get("amount")
        logger.info(f" - {name} ({currency}): {balance}")

    # At this point you can wire in your trading loop safely
    logger.info("Ready to start trading logic (not started by this script).")

if __name__ == "__main__":
    main()
