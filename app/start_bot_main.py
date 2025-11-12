# app/start_bot_main.py
import os
import time
import queue
from loguru import logger
from threading import Thread
from app.nija_client import CoinbaseClient
from app.webhook import start_webhook_server

# Config via env
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") in ("1", "true", "True", "yes")
MIN_TRADE_PERCENT = float(os.getenv("MIN_TRADE_PERCENT", "0.02"))
MAX_TRADE_PERCENT = float(os.getenv("MAX_TRADE_PERCENT", "0.10"))
DEFAULT_TRADE_PERCENT = float(os.getenv("DEFAULT_TRADE_PERCENT", "0.05"))

# Internal signal queue shared between webhook and main loop
SIGNAL_QUEUE_MAX = int(os.getenv("SIGNAL_QUEUE_MAX", "256"))

def calculate_size_from_balance(balance_amount: float, price: float) -> float:
    pct = max(MIN_TRADE_PERCENT, min(MAX_TRADE_PERCENT, DEFAULT_TRADE_PERCENT))
    usd_alloc = balance_amount * pct
    size = usd_alloc / price
    return round(size, 8)

def main_loop(client: CoinbaseClient, signal_queue: "queue.Queue"):
    logger.info("Entering main trading loop...")
    while True:
        try:
            # Try get a signal (non-blocking with short timeout)
            try:
                signal = signal_queue.get(timeout=1.0)
            except queue.Empty:
                signal = None

            # Refresh accounts once per cycle (or use cached + periodic refresh)
            accounts_resp = client.get_accounts()
            # Normalize response: try "data" -> list, or list directly
            if isinstance(accounts_resp, dict) and "data" in accounts_resp:
                accounts = accounts_resp["data"]
            elif isinstance(accounts_resp, list):
                accounts = accounts_resp
            else:
                accounts = accounts_resp

            if not accounts:
                logger.warning("No accounts returned from API.")
                time.sleep(RETRY_DELAY)
                continue

            # select usable account (first with numeric balance)
            selected_account = None
            for a in accounts:
                if isinstance(a, dict):
                    bal = a.get("balance") or a.get("cash_balance") or {}
                    amt = None
                    if isinstance(bal, dict):
                        amt = bal.get("amount")
                    if amt is not None:
                        try:
                            float(amt)
                            selected_account = a
                            break
                        except Exception:
                            pass
            if selected_account is None:
                # fallback: use first item
                selected_account = accounts[0]

            account_id = selected_account.get("id")
            balance_amount = 0.0
            if isinstance(selected_account.get("balance"), dict):
                balance_amount = float(selected_account["balance"].get("amount", 0))
            elif isinstance(selected_account.get("cash_balance"), dict):
                balance_amount = float(selected_account["cash_balance"].get("amount", 0))
            else:
                # if no explicit balance field, keep 0.0 (alerts will skip)
                balance_amount = 0.0

            logger.debug("Account id=%s balance=%s", account_id, balance_amount)

            if signal:
                logger.info("Processing signal from queue: %s", signal)
                side = signal.get("side")
                product_id = signal.get("product_id")
                # Get a market price: attempt to read positions or use orderbook endpoint (not implemented here)
                # This demo tries positions first
                price = None
                try:
                    positions_resp = client.get_positions()
                    if isinstance(positions_resp, dict) and "data" in positions_resp:
                        for p in positions_resp["data"]:
                            # some responses use `product_id` or `symbol`
                            if p.get("product_id") == product_id or p.get("symbol") == product_id:
                                price = float(p.get("current_price") or p.get("market_price") or 0)
                                break
                except Exception:
                    logger.debug("Positions not available or failed")

                if price is None or price == 0:
                    # If you want reliable pricing, add a market price lookup here (not in this snippet)
                    logger.warning("No price available for %s — skipping trade", product_id)
                else:
                    size = calculate_size_from_balance(balance_amount, price)
                    if size <= 0:
                        logger.warning("Calculated size <= 0, skipping")
                    else:
                        logger.info("Placing order: %s %s %s (size=%s)", side, product_id, account_id, size)
                        if LIVE_TRADING:
                            try:
                                order = client.place_order(account_id, side, product_id, size)
                                logger.info("Order placed: %s", order)
                            except Exception as e:
                                logger.error("Order failed: %s", e)
                        else:
                            logger.info("LIVE_TRADING disabled — simulated order: %s", {"side": side, "product_id": product_id, "size": size})
            else:
                # no signal this cycle
                pass

            # small sleep to avoid tight loop
            time.sleep(RETRY_DELAY)

        except Exception as e:
            logger.error("Unhandled error in main loop: %s", e, exc_info=True)
            time.sleep(RETRY_DELAY)

def main():
    logger.info("Starting Nija loader and webhook integration...")
    q = queue.Queue(maxsize=SIGNAL_QUEUE_MAX)

    # start webhook server in background
    start_webhook_server(q)

    # init Coinbase client
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Failed to initialize CoinbaseClient: %s", e)
        return

    # run main loop in current thread
    main_loop(client, q)

if __name__ == "__main__":
    main()
