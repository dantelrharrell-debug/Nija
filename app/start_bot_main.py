# app/start_bot_main.py
import os
import time
from loguru import logger
from nija_client import CoinbaseClient
from requests.exceptions import HTTPError, ConnectionError, Timeout

# Config via env
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") in ("1", "true", "True", "yes")

# Position sizing (use your preferences)
MIN_TRADE_PERCENT = float(os.getenv("MIN_TRADE_PERCENT", "0.02"))  # 2%
MAX_TRADE_PERCENT = float(os.getenv("MAX_TRADE_PERCENT", "0.10"))  # 10%
DEFAULT_TRADE_PERCENT = float(os.getenv("DEFAULT_TRADE_PERCENT", "0.05"))  # 5%

def safe_request(func, *args, **kwargs):
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            status = getattr(e.response, "status_code", None)
            logger.warning("HTTP %s error, attempt %d/%d: %s", status, attempt+1, MAX_RETRIES, e)
            # retry on rate limit and common server errors
            if status in (429, 500, 502, 503, 504, 404):
                attempt += 1
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise
        except (ConnectionError, Timeout) as e:
            logger.warning("Connection error, attempt %d/%d: %s", attempt+1, MAX_RETRIES, e)
            attempt += 1
            time.sleep(RETRY_DELAY * attempt)
        except Exception:
            raise
    raise RuntimeError("Max retries reached in safe_request")

def calculate_size_from_balance(balance_amount: float, price: float) -> float:
    """
    Calculate order size (units of asset) given account balance (in quote currency) and price.
    This uses DEFAULT_TRADE_PERCENT bounded by MIN/MAX.
    """
    pct = max(MIN_TRADE_PERCENT, min(MAX_TRADE_PERCENT, DEFAULT_TRADE_PERCENT))
    usd_alloc = balance_amount * pct
    size = usd_alloc / price
    # round down to reasonable precision for crypto (8 decimals)
    return round(size, 8)

# This placeholder should be replaced by real TradingView / webhook signal parsing
def get_trade_signal():
    """
    Return a trade signal dict or None.
    Example returns:
      {"side": "buy", "product_id": "BTC-USD"}
      {"side": "sell", "product_id": "BTC-USD"}
    """
    # For now, no signals. Replace with webhook listener or native signal fetch.
    return None

def main():
    logger.info("Starting Nija loader (robust)...")
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Failed to init CoinbaseClient: %s", e)
        return

    # persistent run loop
    while True:
        try:
            accounts_resp = safe_request(client.get_accounts)
            # The advanced API returns structured data; attempt to find first usable account
            logger.debug("Raw accounts response: %s", accounts_resp)
            # Try common shapes:
            accounts = None
            if isinstance(accounts_resp, dict) and "data" in accounts_resp:
                accounts = accounts_resp["data"]
            elif isinstance(accounts_resp, list):
                accounts = accounts_resp
            else:
                accounts = accounts_resp

            if not accounts:
                logger.warning("No accounts returned, sleeping %ds then retrying", RETRY_DELAY)
                time.sleep(RETRY_DELAY)
                continue

            # pick first account with usable balance
            account = None
            for a in accounts:
                # common shapes: {'id': ..., 'balance': {'amount': '...'}, ...}
                bal = None
                if isinstance(a, dict):
                    # many advanced endpoints nest the amount
                    bal = a.get("balance", {})
                    if isinstance(bal, dict):
                        amt = bal.get("amount")
                        if amt is not None:
                            try:
                                float(amt)
                                account = a
                                break
                            except Exception:
                                pass
                # fallback: if account has 'id'
                if account is None and isinstance(a, dict) and a.get("id"):
                    account = a
                    break

            if account is None:
                logger.error("No usable account found in response.")
                time.sleep(RETRY_DELAY)
                continue

            account_id = account.get("id")
            balance_amount = None
            if isinstance(account.get("balance"), dict):
                balance_amount = float(account["balance"].get("amount", 0))
            else:
                # some shapes include "cash_balance" or similar
                balance_amount = float(account.get("cash_balance", {}).get("amount", 0)) if isinstance(account.get("cash_balance"), dict) else 0.0

            logger.info("Using account_id=%s balance=%s", account_id, balance_amount)

            # Get positions (optional)
            try:
                positions = safe_request(client.get_positions)
                logger.debug("Positions: %s", positions)
            except Exception as e:
                logger.warning("Could not fetch positions: %s", e)
                positions = None

            # Check for incoming trade signals (replace with your webhook logic)
            signal = get_trade_signal()
            if signal:
                side = signal.get("side")
                product_id = signal.get("product_id")
                # get current price (if available via positions or you should query market price API)
                current_price = None
                # try read from positions (if API exposes current price)
                if positions and isinstance(positions, dict) and "data" in positions and isinstance(positions["data"], list):
                    # find position for product_id
                    for p in positions["data"]:
                        if p.get("product_id") == product_id or p.get("symbol") == product_id:
                            current_price = float(p.get("current_price", 0))
                            break
                # fallback: you must implement a market price lookup (not included here)
                if not current_price:
                    logger.warning("No market price available for %s — skipping order", product_id)
                else:
                    size = calculate_size_from_balance(balance_amount, current_price)
                    if size <= 0:
                        logger.warning("Calculated size <= 0; skipping order")
                    else:
                        logger.info("Placing %s order: product=%s size=%s", side, product_id, size)
                        if LIVE_TRADING:
                            order = safe_request(client.place_order, account_id, side, product_id, size)
                            logger.info("Order placed: %s", order)
                        else:
                            logger.info("LIVE_TRADING disabled — simulated order: %s", {"account_id": account_id, "side": side, "product_id": product_id, "size": size})
            else:
                logger.debug("No trade signal received this cycle.")

            # sleep before the next cycle
            time.sleep(RETRY_DELAY)
        except Exception as e:
            logger.error("Unhandled exception in main loop: %s", e, exc_info=True)
            logger.info("Sleeping %ds before retrying...", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    main()
