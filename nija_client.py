# nija_client.py
import os
import logging
import time
import threading
from queue import Queue, Empty
from typing import Optional, Dict, Any

# Coinbase SDK import (official)
from coinbase.rest import RESTClient
from coinbase.exceptions import CoinbaseAPIError  # if available in your version

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("nija-client")

# --- Trading config (tweak to your preferences) ---
HEARTBEAT_INTERVAL = 30            # seconds
RECONNECT_DELAY = 5                # seconds to wait before trying to reconnect
ORDER_POLL_INTERVAL = 2            # seconds between order checks
DEFAULT_POSITION_SIZE_USD = 100.0  # example sizing; replace with your logic

# --- Signals queue (your external strategy should put signals here) ---
signals_queue: "Queue[Dict[str,Any]]" = Queue()

# --- Helper: read API credentials from environment (preferred) ---
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")

# If you absolutely must hardcode (not recommended), uncomment and set here:
# WARNING: Do NOT commit secrets into source control.
# if not API_KEY:
#     API_KEY = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/ce5dbcbe-ba9f-45a4-a374-5d2618af0ccd"
# if not API_SECRET:
#     API_SECRET = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIC4EDr...YOUR_PRIVATE_KEY...Bg==\n-----END EC PRIVATE KEY-----\n"

# --- Coinbase REST client (managed with reconnect) ---
client: Optional[RESTClient] = None

def build_client() -> Optional[RESTClient]:
    global client
    try:
        if API_KEY and API_SECRET:
            logger.info("Creating RESTClient using provided credentials...")
            # RESTClient will accept api_key / api_secret per README
            client = RESTClient(api_key=API_KEY, api_secret=API_SECRET, timeout=10)
            return client
        else:
            logger.error("No API credentials available in environment variables.")
            return None
    except Exception as e:
        logger.exception("Failed to create RESTClient: %s", e)
        client = None
        return None

def check_and_log_accounts():
    """
    Calls get_accounts and logs currencies + balances so you can confirm funded accounts.
    """
    global client
    if client is None:
        logger.warning("No client available to fetch accounts.")
        return

    try:
        accounts = client.get_accounts()
        # accounts may be a custom response object: try safe ways to inspect it:
        if hasattr(accounts, "to_dict"):
            accounts_dict = accounts.to_dict()
            account_list = accounts_dict.get("accounts", []) or accounts_dict.get("data", []) or accounts_dict
        else:
            # Try direct access of attribute
            account_list = getattr(accounts, "accounts", None) or accounts

        logger.info("Successfully connected to Coinbase. Listing accounts:")
        # Normal structure: list of objects where currency and balance are present
        for a in account_list:
            try:
                # a might be a dict-like or object
                currency = a.get("currency") if isinstance(a, dict) else getattr(a, "currency", None)
                balance_obj = a.get("available_balance") if isinstance(a, dict) else getattr(a, "available_balance", None)
                # Fallback keys:
                if balance_obj is None:
                    balance_obj = a.get("balance") if isinstance(a, dict) else getattr(a, "balance", None)
                value = None
                if isinstance(balance_obj, dict):
                    value = balance_obj.get("value") or balance_obj.get("amount")
                elif hasattr(balance_obj, "__getitem__") and isinstance(balance_obj, (list, tuple)):
                    value = balance_obj[0]
                elif balance_obj is not None and hasattr(balance_obj, "get"):
                    value = balance_obj.get("value") if isinstance(balance_obj, dict) else None
                else:
                    # try dot access
                    value = getattr(a, "available_balance", None) or getattr(a, "balance", None)
                logger.info("Account: %s | Available: %s", currency, value)
            except Exception:
                logger.exception("Error reading account entry: %s", a)
    except Exception as e:
        logger.exception("get_accounts() failed: %s", e)

# --- Order helpers (simple trailing stop / take profit example) ---
def create_market_order(product_id: str, side: str, quote_size: str, client_order_id: str = "") -> Dict:
    """
    Create a market order. Returns order dict/object or raises.
    """
    global client
    if client is None:
        raise RuntimeError("Client not initialized")
    # For buy (side='buy'), quote_size is the USD quote amount as string per README example
    order = client.market_order_buy(client_order_id=client_order_id, product_id=product_id, quote_size=quote_size) if side == "buy" else client.market_order_sell(client_order_id=client_order_id, product_id=product_id, quote_size=quote_size)
    return order.to_dict() if hasattr(order, "to_dict") else order

def poll_order_and_attach_trailing(order_id: str, product_id: str, trailing_stop_pct: float = 0.01, trailing_take_profit_pct: float = 0.02):
    """
    Example lifecycle: poll order status and then simulate trailing stop/take profit by polling product price.
    This is a simple example — for real futures/options you'd use exchange-provided OCO / bracket orders where available.
    """
    global client
    if client is None:
        logger.error("No client to poll order")
        return
    logger.info("Starting order lifecycle monitor for order_id=%s product=%s", order_id, product_id)
    try:
        # Wait until order is filled
        while True:
            order = client.get_order(order_id)
            o = order.to_dict() if hasattr(order, "to_dict") else order
            status = o.get("status") or o.get("state") or getattr(o, "status", None)
            logger.debug("Order status: %s", status)
            if status and status.lower() in ("filled", "done", "executed", "settled"):
                logger.info("Order filled: %s", order_id)
                break
            time.sleep(ORDER_POLL_INTERVAL)
        # Now start trailing logic
        # Grab execution price (attempt multiple keys)
        filled_price = None
        fills = o.get("fills") or o.get("executions") or []
        if fills and isinstance(fills, list):
            try:
                filled_price = float(fills[0].get("price"))
            except Exception:
                pass
        if filled_price is None:
            # fallback: look for avg_filled_price
            filled_price = float(o.get("avg_fill_price") or o.get("filled_avg_price") or 0)
        if filled_price == 0:
            logger.warning("Couldn't determine filled price for order %s; trailing will use market snapshot.", order_id)
        last_trail_price = filled_price
        # trailing thresholds
        trailing_stop = last_trail_price * (1 - trailing_stop_pct)
        take_profit = last_trail_price * (1 + trailing_take_profit_pct)
        logger.info("Trailing monitors started. filled_price=%s stop=%s tp=%s", filled_price, trailing_stop, take_profit)
        # polling product ticker (simple; for production use websocket feed)
        while True:
            product = client.get_product(product_id)
            p = product.to_dict() if hasattr(product, "to_dict") else product
            mark_price = None
            if isinstance(p, dict):
                mark_price = float(p.get("price") or p.get("last") or p.get("mark") or 0)
            else:
                mark_price = float(getattr(p, "price", 0))
            if mark_price == 0:
                logger.debug("No price yet for %s", product_id)
                time.sleep(ORDER_POLL_INTERVAL)
                continue

            # update trailing stop when price moves favorably
            if mark_price > last_trail_price:
                last_trail_price = mark_price
                trailing_stop = last_trail_price * (1 - trailing_stop_pct)
                take_profit = last_trail_price * (1 + trailing_take_profit_pct)
                logger.debug("Trail updated: last_price=%s stop=%s tp=%s", last_trail_price, trailing_stop, take_profit)

            # check TP hit
            if mark_price >= take_profit:
                logger.info("Take profit hit at %s. Submitting sell.", mark_price)
                try:
                    sell_order = client.market_order_sell(client_order_id="", product_id=product_id, quote_size=str(DEFAULT_POSITION_SIZE_USD))
                    logger.info("Take-profit sell placed: %s", getattr(sell_order, "to_dict", lambda: sell_order)())
                except Exception:
                    logger.exception("Failed to place take profit sell")
                break

            # check stop hit
            if mark_price <= trailing_stop:
                logger.info("Trailing stop hit at %s. Submitting sell.", mark_price)
                try:
                    sell_order = client.market_order_sell(client_order_id="", product_id=product_id, quote_size=str(DEFAULT_POSITION_SIZE_USD))
                    logger.info("Trailing stop sell placed: %s", getattr(sell_order, "to_dict", lambda: sell_order)())
                except Exception:
                    logger.exception("Failed to place trailing stop sell")
                break

            time.sleep(ORDER_POLL_INTERVAL)

    except Exception:
        logger.exception("Order lifecycle monitor failed for order %s", order_id)

# --- Worker thread: process signals from your strategy (simplified) ---
def signal_processor_loop():
    """
    Keeps running. Pulls signals from signals_queue and executes them.
    A signal dict example:
    {
        "product_id": "BTC-USD",
        "side": "buy",
        "quote_size": "50",   # USD amount to spend
        "trailing_stop_pct": 0.01,
        "trailing_take_profit_pct": 0.02
    }
    """
    while True:
        try:
            sig = signals_queue.get(timeout=HEARTBEAT_INTERVAL)
        except Empty:
            continue
        try:
            logger.info("Processing signal: %s", sig)
            product_id = sig["product_id"]
            side = sig["side"]
            quote_size = sig.get("quote_size", str(DEFAULT_POSITION_SIZE_USD))
            # place order
            order = create_market_order(product_id=product_id, side=side, quote_size=str(quote_size))
            order_id = order.get("id") or order.get("order_id") or order.get("client_order_id")
            logger.info("Placed order: %s", order)
            # attach trailing monitor in background
            if order_id:
                t = threading.Thread(
                    target=poll_order_and_attach_trailing,
                    args=(order_id, product_id, float(sig.get("trailing_stop_pct", 0.01)), float(sig.get("trailing_take_profit_pct", 0.02))),
                    daemon=True
                )
                t.start()
        except Exception:
            logger.exception("Failed to process signal: %s", sig)
        finally:
            signals_queue.task_done()

# --- Heartbeat / main loop ---
def start_bot():
    global client
    logger.info("NIJA trading bot startup")
    client = build_client()
    if client:
        # Immediately check accounts and log them for confirmation
        check_and_log_accounts()
    else:
        logger.warning("Client not created; running in OFFLINE mode.")

    # start signal processor thread
    processor = threading.Thread(target=signal_processor_loop, daemon=True)
    processor.start()

    # main loop: keep the program alive and show heartbeat
    while True:
        try:
            if client:
                # optional: refresh a lightweight call to ensure auth still valid
                try:
                    client.get_products()  # quick call to confirm API is responsive
                except Exception as e:
                    logger.warning("API ping failed: %s. Attempting to rebuild client.", e)
                    # attempt reconnect
                    time.sleep(RECONNECT_DELAY)
                    client = build_client()
                    if client:
                        check_and_log_accounts()
            else:
                # try to build again if previously failed
                client = build_client()
                if client:
                    check_and_log_accounts()
            logger.info("Bot heartbeat - connected=%s queue_size=%d", bool(client), signals_queue.qsize())
            time.sleep(HEARTBEAT_INTERVAL)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received; exiting.")
            break
        except Exception:
            logger.exception("Unexpected error in main loop; continuing.")
            time.sleep(5)

# --- Example: quick test signal insertion (remove/replace with real strategy) ---
def example_test_signals():
    # This will place a small market buy and then monitor trailing TP/SL
    signals_queue.put({
        "product_id": "BTC-USD",
        "side": "buy",
        "quote_size": "10",                # $10 buy for testing
        "trailing_stop_pct": 0.01,
        "trailing_take_profit_pct": 0.02
    })

if __name__ == "__main__":
    # Dont run example_test_signals() automatically in production; uncomment to test
    # example_test_signals()
    start_bot()
