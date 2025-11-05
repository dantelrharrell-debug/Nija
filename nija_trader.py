#!/usr/bin/env python3
"""
nija_trader.py

Standalone trader helper that:
- Picks the first funded account visible to the API key
- Calculates trade size with your position-sizing rules
- Can place a simple market order (Create Order)
- Provides safe checks and helpful logging for debugging 401 / PEM errors

Usage:
    # Make sure your env is loaded (or export env vars)
    python3 nija_trader.py         # will print funded account info
    python3 nija_trader.py --trade # attempts a single example trade (BTC-USD)

NOTE: This script expects your existing `nija_client.CoinbaseClient` to
implement a `get_all_accounts()` method that returns account dicts from Coinbase.
If your nija_client has a different function name, update the import/calls accordingly.
"""
from __future__ import annotations
import os
import json
import argparse
import logging
from decimal import Decimal

# Use the project's Coinbase client
try:
    from nija_client import CoinbaseClient, calculate_position_size
except Exception as e:
    raise SystemExit(f"❌ Unable to import nija_client: {e}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s")
log = logging.getLogger("nija_trader")


class NijaTrader:
    def __init__(self, risk_factor: float = 5.0, prefer_currency: str | None = None):
        """
        risk_factor: percent-scheme passed to calculate_position_size (interpreted as percent)
                     e.g., 5.0 means 5% (function expects percent-style multiplier).
        prefer_currency: if provided, prefer this currency when choosing funded account (e.g. "USD" or "BTC")
        """
        self.risk_factor = float(risk_factor)
        self.prefer_currency = prefer_currency
        try:
            self.client = CoinbaseClient()
        except Exception as e:
            log.error("❌ Error creating CoinbaseClient: %s", e)
            raise

        # pick a funded account on init
        self.funded_account = self._find_funded_account()
        if not self.funded_account:
            raise RuntimeError("⚠️ No funded accounts found for this API key. Check permissions & accounts.")

        # normalize account info
        self.currency = self.funded_account.get("currency")
        self.balance = Decimal(self.funded_account.get("balance", {}).get("amount", "0"))
        log.info("✅ Trading from account: %s (balance: %s)", self.currency, str(self.balance))

    def _find_funded_account(self):
        """
        Inspect all accounts visible to the API key and return the best candidate:
        - If prefer_currency is set, prefer accounts with that currency and non-zero balance.
        - Otherwise return the first account with balance > 0 (sorted by balance desc).
        """
        try:
            accounts = self.client.get_all_accounts()
        except Exception as e:
            log.error("❌ Failed to fetch accounts: %s", e)
            # bubble the exception up
            raise

        # defensive: ensure accounts is list-like
        if not isinstance(accounts, list):
            log.debug("Accounts response not list-like; attempting to extract 'data' key.")
            if isinstance(accounts, dict) and "data" in accounts:
                accounts = accounts["data"]
            else:
                raise RuntimeError("Unexpected accounts structure returned from client.")

        # filter numeric balances > 0
        funded = []
        for acc in accounts:
            try:
                amt = Decimal(acc.get("balance", {}).get("amount", "0"))
            except Exception:
                amt = Decimal("0")
            if amt > 0:
                funded.append((amt, acc))

        if not funded:
            return None

        # prefer currency if requested
        if self.prefer_currency:
            # case-insensitive match
            for amt, acc in sorted(funded, key=lambda x: x[0], reverse=True):
                if acc.get("currency", "").upper() == self.prefer_currency.upper():
                    return acc

        # else return account with largest balance
        funded_sorted = sorted(funded, key=lambda x: x[0], reverse=True)
        return funded_sorted[0][1]

    def calculate_trade_size(self) -> Decimal:
        """
        Use calculate_position_size helper:
          calculate_position_size(account_equity, risk_factor,
                                  min_percent=2, max_percent=10)
        NOTE: The calculate_position_size you provided uses risk_factor as percent.
        """
        # If Coinbase balance returned as zero or not present, raise.
        if self.balance <= 0:
            raise RuntimeError("Account balance must be > 0 to calculate trade size.")

        # calculate_position_size returns a float in USD; convert to Decimal for safety
        trade_usd = calculate_position_size(float(self.balance), risk_factor=self.risk_factor, min_percent=2, max_percent=10)
        trade_usd = Decimal(str(trade_usd))
        log.info("🔢 Calculated trade size: %s %s-equivalent (risk=%s%%)", trade_usd, "USD", self.risk_factor)
        return trade_usd

    def place_order(self, product_id: str, side: str, order_type: str = "market", size_usd: Decimal | None = None):
        """
        Place a market order using the Advanced Trade POST /orders endpoint.
        This implementation sends a JSON body like:
            { "product_id": "BTC-USD", "side": "BUY", "type": "market", "size": "10.00" }
        NOTE: Depending on your Coinbase endpoints, you may need to use different field names
        (e.g. "amount", "funds", "size" or trading API differences). Adjust as needed.
        """
        side = side.upper()
        if size_usd is None:
            size_usd = self.calculate_trade_size()

        endpoint = "/v2/orders"  # keep consistent with your client
        body = {
            "product_id": product_id,
            "side": side,
            "type": order_type,
            # size interpreted as USD amount (if API expects quote size). If exchange expects base size,
            # you must convert USD -> coin size by fetching market price first.
            "size": str(size_usd)
        }
        body_json = json.dumps(body)

        # Use client JWT helper if available; otherwise attempt a direct Authorization header
        headers = {"Content-Type": "application/json"}
        try:
            if hasattr(self.client, "_generate_jwt"):
                headers["Authorization"] = f"Bearer {self.client._generate_jwt('POST', endpoint, body_json)}"
            elif hasattr(self.client, "get_bearer_token"):
                headers["Authorization"] = f"Bearer {self.client.get_bearer_token()}"
            else:
                # fallback: rely on client to send requests (if it exposes a request helper)
                pass
        except Exception as e:
            log.warning("⚠️ Could not create Authorization header via client: %s", e)

        # Do the HTTP call using requests to your configured base_url
        import requests
        url = (os.getenv("COINBASE_API_BASE") or self.client.base_url) + endpoint
        log.info("➡️ Placing order: %s %s of %s -> %s", side, size_usd, product_id, url)
        try:
            resp = requests.post(url, headers=headers, data=body_json, timeout=15)
        except Exception as e:
            log.error("❌ HTTP request failed while placing order: %s", e)
            return None

        if resp.ok:
            log.info("✅ Order placed successfully: %s", resp.text)
            try:
                return resp.json()
            except Exception:
                return resp.text
        else:
            log.error("❌ Order failed: %s %s", resp.status_code, resp.text)
            # helpful hint for auth problems:
            if resp.status_code in (401, 403):
                log.error("🔍 401/403 detected. Check API key permissions (View + Trade) and JWT vs classic key usage.")
            return None


def main():
    parser = argparse.ArgumentParser(prog="nija_trader", description="Nija trader helper")
    parser.add_argument("--risk", type=float, default=5.0, help="risk percent for position sizing (default 5)")
    parser.add_argument("--prefer", type=str, default=None, help="prefer this currency when picking funded account (e.g. 'USD')")
    parser.add_argument("--trade", action="store_true", help="attempt a demo trade (BTC-USD) using calculated position size")
    args = parser.parse_args()

    try:
        trader = NijaTrader(risk_factor=args.risk, prefer_currency=args.prefer)
    except Exception as e:
        log.error("❌ Failed to initialize trader: %s", e)
        return

    # show funded account details
    log.info("🔹 Funded account chosen: %s", trader.funded_account)
    if args.trade:
        # Example trade
        product_id = "BTC-USD"
        side = "buy"
        try:
            size = trader.calculate_trade_size()
            result = trader.place_order(product_id=product_id, side=side, size_usd=size)
            log.info("Trade result: %s", result)
        except Exception as e:
            log.error("❌ Trade attempt failed: %s", e)


if __name__ == "__main__":
    main()
