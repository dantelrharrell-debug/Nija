#!/usr/bin/env python3
"""
Nija main trading bootstrap + webhook + simple live-trade loop.

Paste this file as main.py in your project root and set the env vars described in the README above.
"""

import os
import time
import json
import logging
import threading
from typing import Optional, Dict, Any

import requests
import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from flask import Flask, request, jsonify

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("nija_trader")

# --- Env / config ---
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")  # used as kid
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", "")
LIVE_TRADING = os.getenv("LIVE_TRADING", "0").strip() == "1"
MIN_POSITION_PCT = float(os.getenv("MIN_POSITION_PCT", "0.02"))  # 2% default
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))  # 10% default
PORT = int(os.getenv("PORT", "8080"))

# Basic validation
if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_PEM_CONTENT:
    log.warning("Missing one of COINBASE_ORG_ID / COINBASE_API_KEY_ID / COINBASE_PEM_CONTENT in env. "
                "Load them before starting.")

# --- Helpers for PEM/JWT ---
def normalize_pem(pem_text: str) -> str:
    """Make sure PEM starts/ends properly and newlines are correct."""
    if not pem_text:
        raise ValueError("Empty PEM")
    # If it's wrapped in single quotes or includes stray characters, sanitize
    pem = pem_text.strip()
    # Replace literal \n sequences with newlines if user used single-line escaped env
    if "\\n" in pem and "-----BEGIN" in pem:
        pem = pem.replace("\\n", "\n")
    # Ensure header/footer present
    if "-----BEGIN" not in pem:
        raise ValueError("PEM missing header")
    # Ensure ends with newline
    if not pem.endswith("\n"):
        pem += "\n"
    return pem

def load_private_key(pem_text: str):
    """Return private key object (cryptography) - used for extra validation if needed."""
    pem = normalize_pem(pem_text)
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None, backend=default_backend())
        return key
    except Exception as e:
        log.exception("Unable to load PEM: %s", e)
        raise

def build_jwt(kid: str, org: str, pem_text: str, ttl_seconds: int = 60) -> str:
    """
    Build ES256 JWT for Coinbase Advanced auth.
    Header uses 'kid' = API key id.
    Sub = /organizations/{org}/apiKeys/{kid}
    """
    pem = normalize_pem(pem_text)
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + ttl_seconds,
        "sub": f"/organizations/{org}/apiKeys/{kid}",
        "request_path": f"/api/v3/brokerage/organizations/{org}/key_permissions",
        "method": "GET",
        "jti": f"nija-{now}"
    }
    headers = {"kid": kid, "typ": "JWT", "alg": "ES256"}
    token = jwt.encode(payload, pem, algorithm="ES256", headers=headers)
    # PyJWT returns str in modern versions
    return token

# --- Coinbase minimal client ---
class CoinbaseClient:
    def __init__(self, api_base: str, org_id: str, api_key_id: str, pem_content: str):
        self.api_base = api_base.rstrip("/")
        self.org_id = org_id
        self.api_key_id = api_key_id
        self.pem_content = pem_content
        # Try to load key right away for early failure
        try:
            self._key_obj = load_private_key(pem_content)
            log.info("✅ PEM loaded and API key present")
        except Exception as e:
            log.warning("PEM load failed at init: %s", e)
            self._key_obj = None

    def generate_jwt(self, ttl_seconds: int = 60) -> str:
        return build_jwt(self.api_key_id, self.org_id, self.pem_content, ttl_seconds=ttl_seconds)

    def validate_key_permissions(self) -> Dict[str, Any]:
        """Call key_permissions endpoint to validate JWT auth works."""
        jwt_token = self.generate_jwt()
        url = f"{self.api_base}/api/v3/brokerage/organizations/{self.org_id}/key_permissions"
        headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
        resp = requests.get(url, headers=headers, timeout=10)
        try:
            body = resp.json()
        except Exception:
            body = {"text": resp.text}
        return {"status": resp.status_code, "body": body, "text": resp.text}

    def fetch_accounts(self) -> Dict[str, Any]:
        """Example: fetch brokerage accounts (may require different endpoint depending on Coinbase product)"""
        jwt_token = self.generate_jwt()
        url = f"{self.api_base}/api/v3/brokerage/organizations/{self.org_id}/accounts"
        headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
        resp = requests.get(url, headers=headers, timeout=10)
        try:
            return resp.json()
        except Exception:
            return {"status": resp.status_code, "text": resp.text}

    def place_order_market(self, account_id: str, symbol: str, side: str, size_currency: float) -> Dict[str, Any]:
        """Place a market order. This is example code — ensure your account/endpoint and order body match Coinbase's API."""
        jwt_token = self.generate_jwt()
        url = f"{self.api_base}/api/v3/brokerage/accounts/{account_id}/orders"
        headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
        body = {
            "type": "market",
            "symbol": symbol,
            "side": side.lower(),  # 'buy' or 'sell'
            # we'll send a simple body with amount in native currency (adjust to API's required fields)
            "amount": str(size_currency)
        }
        log.info("Placing order (LIVE=%s) %s", LIVE_TRADING, body)
        if not LIVE_TRADING:
            return {"dry_run": True, "body": body}
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        try:
            return resp.json()
        except Exception:
            return {"status": resp.status_code, "text": resp.text}

# --- Utility: sizing and account pick ---
def calc_order_size_usd(account_balance_usd: float, pct: float) -> float:
    """Return USD size for a given % of account equity (clamped)."""
    pct = max(MIN_POSITION_PCT, min(MAX_POSITION_PCT, pct))
    return account_balance_usd * pct

def pick_account(accounts_resp: dict) -> Optional[str]:
    """Pick first suitable account id from Coinbase accounts response. Adapt if response schema differs."""
    if not isinstance(accounts_resp, dict):
        return None
    items = accounts_resp.get("accounts") or accounts_resp.get("data") or []
    if not items:
        # try if response is list
        if isinstance(accounts_resp, list) and accounts_resp:
            first = accounts_resp[0]
            return first.get("id") or first.get("account_id")
        return None
    first = items[0]
    return first.get("id") or first.get("account_id")

# --- test helper requested earlier ---
def test_coinbase_connection(client: CoinbaseClient) -> bool:
    try:
        res = client.validate_key_permissions()
        log.info("✅ Coinbase key validation response: %s", res.get("status"))
        if res.get("status") == 200:
            # attempt to fetch accounts
            accounts = client.fetch_accounts()
            log.info("✅ Accounts fetch (sample): %s", ("ok" if accounts else "empty"))
            return True
        else:
            log.error("❌ Coinbase key validation failed: %s", res.get("body") or res.get("text"))
            return False
    except Exception as e:
        log.exception("❌ Coinbase connection failed: %s", e)
        return False

# --- Webhook server to receive signals (TradingView JSON format typical) ---
app = Flask("nija_webhook")
received_signals = []  # small in-memory queue

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True)
    except Exception:
        payload = {"raw": request.data.decode("utf-8")}
    log.info("Webhook signal received: %s", payload if isinstance(payload, dict) else str(payload)[:200])
    # Basic validation
    sig = {
        "timestamp": int(time.time()),
        "payload": payload
    }
    received_signals.append(sig)
    return jsonify({"ok": True}), 200

def start_flask_thread():
    th = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True)
    th.start()
    log.info("Webhook server started on port %s", PORT)

# --- Main trading loop ---
def trading_loop(client: CoinbaseClient):
    log.info("Entering trading loop. LIVE_TRADING=%s", LIVE_TRADING)
    account_id = None
    # try to find account
    try:
        accounts = client.fetch_accounts()
        account_id = os.getenv("TRADING_ACCOUNT_ID") or pick_account(accounts)
        if not account_id:
            log.warning("No account id found automatically. Set TRADING_ACCOUNT_ID env var.")
        else:
            log.info("Using trading account id: %s", account_id)
    except Exception as e:
        log.exception("Failed to fetch accounts: %s", e)

    while True:
        # 1) priority: any webhook signals
        if received_signals:
            sig = received_signals.pop(0)
            handle_signal(sig, client, account_id)
            continue

        # 2) fallback: check file /tmp/next_signal.json if present (developer-friendly)
        fn = "/tmp/next_signal.json"
        if os.path.exists(fn):
            try:
                with open(fn, "r") as f:
                    payload = json.load(f)
                os.remove(fn)
                sig = {"timestamp": int(time.time()), "payload": payload}
                handle_signal(sig, client, account_id)
                continue
            except Exception as e:
                log.exception("Error reading /tmp/next_signal.json: %s", e)

        # idle sleep
        time.sleep(1)

def handle_signal(signal: dict, client: CoinbaseClient, account_id: Optional[str]):
    payload = signal.get("payload") or {}
    log.info("Processing signal payload: %s", payload)
    # Minimal expected: {"action":"BUY","symbol":"BTC-USD","risk_pct":0.03}
    action = None
    symbol = None
    risk_pct = None
    if isinstance(payload, dict):
        action = payload.get("action") or payload.get("side") or payload.get("signal")
        symbol = payload.get("symbol") or payload.get("ticker") or payload.get("pair")
        risk_pct = float(payload.get("risk_pct")) if payload.get("risk_pct") else float(payload.get("size_pct") or 0.0)
    # tolerant parsing for TradingView messages
    if not action and isinstance(payload, str):
        text = payload.lower()
        if "buy" in text:
            action = "buy"
        elif "sell" in text:
            action = "sell"
    if not action or not symbol:
        log.warning("Signal missing action or symbol; skipping. payload=%s", payload)
        return

    # fetch account balance (simplified - adjust to your API)
    account_balance_usd = 1000.0  # fallback if we can't fetch
    if account_id:
        try:
            # This endpoint/field may differ in your Coinbase product, adjust if needed
            acct_resp = client.fetch_accounts()
            # naive extraction
            items = acct_resp.get("accounts") or acct_resp.get("data") or []
            if items:
                # try to find matching account
                found = None
                for a in items:
                    if a.get("id") == account_id:
                        found = a; break
                if not found:
                    found = items[0]
                # attempt to parse balance
                bal = found.get("balance") or found.get("cash_balance") or found.get("available_balance")
                if isinstance(bal, dict):
                    account_balance_usd = float(bal.get("amount") or bal.get("value") or account_balance_usd)
                else:
                    # if numeric string
                    account_balance_usd = float(bal or account_balance_usd)
        except Exception:
            log.exception("Failed to detect account balance; using fallback.")

    # determine size
    pct = risk_pct if risk_pct and risk_pct > 0 else MIN_POSITION_PCT
    size_usd = calc_order_size_usd(account_balance_usd, pct)
    log.info("Calculated trade size: USD %.2f (pct=%.3f of balance %.2f)", size_usd, pct, account_balance_usd)

    # Place order (market)
    resp = client.place_order_market(account_id or "UNKNOWN", symbol, action, size_currency=size_usd)
    log.info("Order response: %s", resp)

# --- Entrypoint ---
def main():
    client = CoinbaseClient(COINBASE_API_BASE, COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT)
    # quick validation attempt
    try:
        ok = test_coinbase_connection(client)
        if not ok:
            log.warning("Coinbase connection test failed. Check IP whitelist and envs.")
        else:
            log.info("Coinbase connection test OK.")
    except Exception:
        log.exception("Connection test raised.")

    # start webhook server
    start_flask_thread()

    # start trading loop
    trading_loop(client)

if __name__ == "__main__":
    main()
