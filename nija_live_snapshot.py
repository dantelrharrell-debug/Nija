#!/usr/bin/env python3
# nija_live_snapshot.py

import logging
from nija_client import client, start_trading

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logging.info("🌟 Nija bot is starting...")


# -----------------------------
# Helper: robust balance extractor
# -----------------------------
def _balance_amount(account):
    """
    Return a string amount for an account regardless of shape:
    - account['balance'] may be a dict {'amount': '123.45', ...}
    - or a string '123.45'
    - or a numeric 123.45
    - or an object with .amount attribute
    - or account may be object-like with .balance
    """
    try:
        # accept dict-like or object-like
        if isinstance(account, dict):
            bal = account.get("balance", None) or account.get("available", None)
        else:
            bal = getattr(account, "balance", None) or getattr(account, "available", None)

        # dict with amount
        if isinstance(bal, dict) and "amount" in bal:
            return str(bal["amount"])

        # numeric
        if isinstance(bal, (int, float)):
            return str(bal)

        # string
        if isinstance(bal, str):
            return bal

        # object-like with .amount
        try:
            amt = getattr(bal, "amount", None)
            if amt is not None:
                return str(amt)
        except Exception:
            pass

        # fallback: check account.available if dict
        if isinstance(account, dict):
            avail = account.get("available")
            if isinstance(avail, dict) and "amount" in avail:
                return str(avail["amount"])
            if isinstance(avail, (str, int, float)):
                return str(avail)

        return "0"
    except Exception:
        return "0"


# -----------------------------
# Quick connectivity test (robust)
# -----------------------------
try:
    accounts = client.get_accounts()
    if accounts:
        logging.info("✅ Successfully connected to Coinbase API. Accounts detected:")
        for account in accounts:
            try:
                # robustly get currency
                currency = account.get("currency") if isinstance(account, dict) else getattr(account, "currency", None)
                amount = _balance_amount(account)
                logging.info(f" - {currency}: {amount}")
            except Exception:
                logging.exception("Failed to log account safely")
    else:
        logging.warning("⚠️ Connected to Coinbase API, but no accounts returned.")
except Exception as e:
    logging.exception(f"❌ Failed to connect to Coinbase API: {e}")
    raise SystemExit("Cannot continue without Coinbase connection.")


# -----------------------------
# Start trading loop
# -----------------------------
start_trading()
