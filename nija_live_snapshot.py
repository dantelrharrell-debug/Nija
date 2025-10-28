#!/usr/bin/env python3
# nija_live_snapshot.py

import logging
from nija_client import client, start_trading, get_accounts

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logging.info("🌟 Nija bot is starting...")

# -----------------------------
# Quick connectivity test
# -----------------------------
try:
    accounts = get_accounts()
    if accounts:
        logging.info("✅ Successfully connected to Coinbase API. Accounts detected:")
        for account in accounts:
            logging.info(f" - {account['currency']}: {account['balance']['amount']}")
    else:
        logging.warning("⚠️ Connected to Coinbase API, but no accounts returned.")
except Exception as e:
    logging.exception(f"❌ Failed to connect to Coinbase API: {e}")
    raise SystemExit("Cannot continue without Coinbase connection.")

# -----------------------------
# Start trading loop
# -----------------------------
start_trading()
logging.info("🔥 Nija trading loop is now live 🔥")
