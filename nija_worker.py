# nija_worker.py
import os
import logging
import time
from decimal import Decimal, ROUND_DOWN
import requests
import smtplib
from email.mime.text import MIMEText

# -------------------------
# Logger setup
# -------------------------
logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# File logger for trades
trade_logger = logging.getLogger("nija_trades")
trade_logger.setLevel(logging.INFO)
if not trade_logger.handlers:
    file_handler = logging.FileHandler("nija_trades.log")
    formatter = logging.Formatter("%(asctime)s - %(message)s")
    file_handler.setFormatter(formatter)
    trade_logger.addHandler(file_handler)

# -------------------------
# Configurable environment vars
# -------------------------
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")
MIN_PCT = float(os.getenv("TRADE_MIN_PCT", "0.02"))   # 2%
MAX_PCT = float(os.getenv("TRADE_MAX_PCT", "0.10"))   # 10%
MIN_USD = float(os.getenv("TRADE_MIN_USD", "1"))      # $1
SLEEP_SECONDS = int(os.getenv("WORKER_LOOP_SLEEP", "10"))

logger.info(f"[NIJA] Worker config DRY_RUN={DRY_RUN} MIN_PCT={MIN_PCT} MAX_PCT={MAX_PCT} MIN_USD={MIN_USD}")

# -------------------------
# Discord & Email config
# -------------------------
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO", "dantelrharrell@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def send_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
    except Exception as e:
        logger.warning(f"[NIJA] Discord send failed: {e}")

def send_email(subject: str, body: str):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    except Exception as e:
        logger.warning(f"[NIJA] Email send failed: {e}")

# -------------------------
# Import live client
# -------------------------
try:
    from coinbase_advanced_py.client import CoinbaseClient
    client = CoinbaseClient()  # picks up env keys automatically
    USE_DUMMY = False
    logger.info("[NIJA] Using Live CoinbaseClient — live trading enabled")
except Exception:
    from dummy_client import DummyClient
    client = DummyClient()
    USE_DUMMY = True
    logger.warning("[NIJA] Live client not available — using DummyClient (no live trades)")

# -------------------------
# Trading logic import
# -------------------------
try:
    from trading_logic import decide_trade
    logger.info("[NIJA] trading_logic.decide_trade loaded")
except Exception:
    decide_trade = None
    logger.warning("[NIJA] trading_logic.decide_trade NOT found — worker will skip trades until added")

# -------------------------
# Helper functions
# -------------------------
def get_usd_balance(client):
    try:
        if hasattr(client, "get_account_balances"):
            b = client.get_account_balances()
            return Decimal(str(b.get("USD", 0)))
    except Exception as e:
        logger.warning(f"[NIJA] get_usd_balance error: {e}")
    return None

def get_price_for_product(client, product_id):
    try:
        if hasattr(client, "get_ticker"):
            res = client.get_ticker(product_id)
            return Decimal(str(res.get("price", res.get("last", 0))))
    except Exception:
        return None
    return None

def place_market_order(client, action, product_id, usd_amount):
    logger.info(f"[NIJA] Placing MARKET {action.upper()} for {product_id} US${usd_amount}")
    kwargs = {"product_id": product_id, "funds": str(usd_amount)}
    candidates = [
        ("market_order_buy", lambda c: getattr(c, "market_order_buy", None) and c.market_order_buy(**{"product_id":product_id, "usd":str(usd_amount)})),
        ("market_order", lambda c: getattr(c, "market_order", None) and c.market_order(side=action, product_id=product_id, funds=str(usd_amount))),
        ("buy", lambda c: getattr(c, "buy", None) and c.buy(amount=str(usd_amount), product_id=product_id)),
        ("place_order", lambda c: getattr(c, "place_order", None) and c.place_order(side=action, product_id=product_id, funds=str(usd_amount))),
    ]
    last_exc = None
    for name, fn in candidates:
        try:
            method = fn(client)
            if method is not None:
                logger.info(f"[NIJA] Used method {name} to place order")
                return method
        except Exception as e:
            last_exc = e
    raise RuntimeError(f"No supported order method found (last error: {last_exc})")

def clamp(n, minn, maxn):
    return max(minn, min(maxn, n))

# -------------------------
# Main live trading loop
# -------------------------
def start_worker(client):
    logger.info("[NIJA] Starting live trading worker")
    while True:
        try:
            signal = None
            if decide_trade:
                try:
                    signal = decide_trade(client)
                except Exception as e:
                    logger.error(f"[NIJA] trading_logic.decide_trade error: {e}")
                    signal = None

            if signal:
                action = str(signal.get("action")).lower()
                product_id = signal.get("product_id")
                confidence = float(signal.get("confidence", 1.0))

                usd_balance = get_usd_balance(client)
                if usd_balance is None or usd_balance < MIN_USD:
                    logger.warning("[NIJA] USD balance too low — skipping trade")
                else:
                    pct = clamp(confidence * MAX_PCT, MIN_PCT, MAX_PCT)
                    usd_to_use = (usd_balance * Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                    if usd_to_use < MIN_USD:
                        logger.warning(f"[NIJA] Computed order ${usd_to_use} below MIN_USD; skipping")
                    else:
                        if DRY_RUN or USE_DUMMY:
                            logger.info(f"[NIJA] DRY_RUN enabled — would place {action} for ${usd_to_use} on {product_id}")
                        else:
                            try:
                                result = place_market_order(client, action, product_id, usd_to_use)
                                logger.info(f"[NIJA] Order executed: {result}")
                                trade_logger.info(f"{action.upper()} ${usd_to_use} {product_id} — result: {result}")
                                send_discord(f"NIJA TRADE: {action.upper()} ${usd_to_use} {product_id}")
                                send_email(f"NIJA TRADE: {action.upper()} {product_id}",
                                           f"Executed {action.upper()} for ${usd_to_use} on {product_id}. Result:\n{result}")
                            except Exception as e:
                                logger.error(f"[NIJA] Failed to place order: {e}")
            time.sleep(SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted; exiting cleanly")
            break
        except Exception as e:
            logger.exception(f"[NIJA] Worker loop error: {e}")
            time.sleep(5)

# -------------------------
# Start the bot
# -------------------------
if __name__ == "__main__":
    start_worker(client)
