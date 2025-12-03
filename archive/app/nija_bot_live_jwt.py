# nija_bot_live_jwt.py
import os
import time
import asyncio
import logging
import json
import aiohttp
import pandas as pd
import jwt  # pyjwt with crypto support required

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nija.bot.jwt")

# ---------- Config ----------
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
COINBASE_ISS = os.getenv("COINBASE_ISS")  # organization / key id e.g. organizations/.../apiKeys/...
COINBASE_PRIVATE_KEY_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # optional instead of path

# Safety check
if not COINBASE_ISS:
    raise SystemExit("Set COINBASE_ISS in environment (.env) before running.")

# Load private key (PEM)
_private_key = None
if COINBASE_PEM_CONTENT:
    _private_key = COINBASE_PEM_CONTENT.strip().encode()
elif COINBASE_PRIVATE_KEY_PATH and os.path.exists(COINBASE_PRIVATE_KEY_PATH):
    with open(COINBASE_PRIVATE_KEY_PATH, "rb") as f:
        _private_key = f.read()
else:
    logger.warning("PEM not found: set COINBASE_PRIVATE_KEY_PATH or COINBASE_PEM_CONTENT in .env")
    # we won't raise here so user can see the warning in logs — but bot will fail auth until provided.

# ---------- Trading config ----------
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]

MIN_ALLOCATION = 0.02
MAX_ALLOCATION = 0.10
VOLATILITY_FACTOR = 0.5

FAST_VWAP_WINDOW = 5
SLOW_VWAP_WINDOW = 20
RSI_PERIOD = 14

TRADE_STATE = {}           # TRADE_STATE[account_id][symbol] = {...}
LAST_SYMBOL_CHECK = {}     # per-symbol rate limiting timestamps

# ---------- JWT helper ----------
def generate_jwt(method: str, path: str, exp_seconds: int = 120) -> str:
    """
    Generate a short lived ES256 JWT for Coinbase Advanced request.
    payload structure follows Coinbase JWT examples: iss, sub, iat, nbf, exp, uri
    """
    if not _private_key:
        raise RuntimeError("Private key not loaded (COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH).")

    now_ts = int(time.time())
    payload = {
        "iss": COINBASE_ISS,
        "sub": COINBASE_ISS,
        "nbf": now_ts,
        "iat": now_ts,
        "exp": now_ts + exp_seconds,
        # Note: Coinbase examples include uri as "<METHOD> <FULL_URL>".
        "uri": f"{method.upper()} {COINBASE_API_BASE}{path}"
    }
    token = jwt.encode(payload, _private_key, algorithm="ES256")
    # pyjwt returns str on modern versions; ensure str
    if isinstance(token, bytes):
        token = token.decode()
    return token

# ---------- HTTP wrapper using JWT ----------
async def cb_request_jwt(method: str, path: str, data: dict | None = None, timeout: int = 20):
    """
    Send a request signed by a short-lived JWT in Authorization: Bearer <token>.
    Returns JSON or None on error.
    """
    url = COINBASE_API_BASE + path
    body = json.dumps(data) if data else None
    try:
        token = generate_jwt(method, path)
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.request(method, url, headers=headers, data=body) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.warning(f"HTTP {resp.status} {path} -> {text}")
                    return None
                # sometimes APIs return JSON list/object
                try:
                    return await resp.json()
                except Exception:
                    # return raw text if json decode fails
                    return text
    except Exception as e:
        logger.error(f"Network error calling {path}: {e}")
        return None

# ---------- Data fetchers & indicators ----------
async def list_accounts():
    """
    Try endpoints in order known for Coinbase/CDP:
      1) /platform/v1/wallets (wallets endpoint used in some docs)
      2) /accounts (generic)
    Returns list of account objects (or empty list).
    """
    # prefer wallets path first (some CDP setups use it)
    for path in ("/platform/v1/wallets", "/accounts"):
        res = await cb_request_jwt("GET", path)
        if res:
            # If wallets endpoint returns nested structure, normalize to list of dicts
            if isinstance(res, dict) and "data" in res and isinstance(res["data"], list):
                return res["data"]
            if isinstance(res, list):
                return res
            if isinstance(res, dict):
                # sometimes dict of accounts keyed by id
                return [res]
    return []

async def fetch_prices(symbol):
    path = f"/market_data/{symbol}/candles?granularity=60"
    resp = await cb_request_jwt("GET", path)
    if not resp:
        return []
    # Expect resp either list of candle objects or list-of-lists depending on API;
    # We assume each item contains 'close' or is [time, low, high, open, close, volume] — try to be flexible.
    try:
        df = pd.DataFrame(resp)
        if "close" in df.columns:
            df["close"] = df["close"].astype(float)
            return df["close"].tolist()
        # fallback: if data is nested lists (time, low, high, open, close, volume) -> close index 4
        if df.shape[1] >= 5:
            closes = df.iloc[:, 4].astype(float).tolist()
            return closes
    except Exception:
        logger.debug("Could not parse price response into DataFrame")
    return []

def compute_vwap(prices):
    return sum(prices) / len(prices)

def compute_fast_slow_vwap(prices):
    fast = compute_vwap(prices[-FAST_VWAP_WINDOW:]) if len(prices) >= FAST_VWAP_WINDOW else compute_vwap(prices)
    slow = compute_vwap(prices[-SLOW_VWAP_WINDOW:]) if len(prices) >= SLOW_VWAP_WINDOW else compute_vwap(prices)
    return fast, slow

def compute_rsi(prices, period=RSI_PERIOD):
    s = pd.Series(prices)
    deltas = s.diff().dropna()
    gain = deltas.clip(lower=0).rolling(period).mean()
    loss = -deltas.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0

def compute_volatility(prices):
    return float(pd.Series(prices).pct_change().std())

def get_trade_size(balance, allocation, volatility):
    size = balance * allocation * (1 - volatility * VOLATILITY_FACTOR)
    return max(size, 0.0)

# ---------- Orders ----------
async def place_order(account_id: str, side: str, symbol: str, size: float):
    # Many CDP endpoints require the account id in the body or path; adapt as necessary for your account type.
    # We'll attempt a generic /orders POST with optional metadata referencing account_id.
    data = {
        "side": side,
        "symbol": symbol,
        "size": str(round(size, 8)),  # send as string for safety
        "account_id": account_id
    }
    res = await cb_request_jwt("POST", "/orders", data)
    return res

# ---------- Trailing & trade management ----------
async def check_trailing(account_id, symbol, prices):
    st = TRADE_STATE.get(account_id, {}).get(symbol)
    if not st:
        return
    side = st["side"]; entry = st["entry"]; ttp = st["ttp"]; tsl = st["tsl"]; size = st["size"]
    price = prices[-1]
    if side == "buy":
        if price > ttp: st["ttp"] = price * 0.99
        if price - entry > 0: st["tsl"] = max(tsl, price * 0.98)
        if price < st["tsl"] or price < st["ttp"]:
            await place_order(account_id, "sell", symbol, size)
            TRADE_STATE[account_id].pop(symbol, None)
            logger.info(f"[{account_id}] {symbol} BUY exited (TTP/TSL)")
    else:  # sell
        if price < ttp: st["ttp"] = price * 1.01
        if entry - price > 0: st["tsl"] = min(tsl, price * 1.02)
        if price > st["tsl"] or price > st["ttp"]:
            await place_order(account_id, "buy", symbol, size)
            TRADE_STATE[account_id].pop(symbol, None)
            logger.info(f"[{account_id}] {symbol} SELL exited (TTP/TSL)")

# ---------- Per-account symbol trading ----------
async def trade_account_symbol(account: dict, symbol: str):
    acct_id = account.get("id") or account.get("account_id") or account.get("wallet_id") or account.get("ledger_id") or "main"
    # parse available balance USD if present, fallback to total balance
    balance = 0.0
    try:
        # Many account shapes: {currency, balance: {available}} or {balance, available}
        if "balance" in account and isinstance(account["balance"], dict):
            # could be USD wallet, else sum of USD-like balances isn't trivial here
            # attempt to use 'available' numeric if present
            available = account["balance"].get("available")
            if available is not None:
                balance = float(available)
        elif "available" in account:
            balance = float(account["available"])
        elif "balance" in account:
            balance = float(account["balance"])
    except Exception:
        balance = 0.0

    if balance <= 0:
        logger.debug(f"[{acct_id}] balance zero or unavailable, skipping symbol {symbol}")
        return

    # rate-limit: small stagger per symbol to avoid bursts
    last = LAST_SYMBOL_CHECK.get(symbol, 0)
    now = time.time()
    wait = max(0, 1 - (now - last))  # at least 1 second between same-symbol checks
    if wait > 0:
        await asyncio.sleep(wait)
    LAST_SYMBOL_CHECK[symbol] = time.time()

    prices = await fetch_prices(symbol)
    if not prices or len(prices) < SLOW_VWAP_WINDOW:
        return

    fast_vwap, slow_vwap = compute_fast_slow_vwap(prices)
    rsi = compute_rsi(prices)
    vol = compute_volatility(prices)
    allocation = min(MAX_ALLOCATION, max(MIN_ALLOCATION, rsi / 100))
    trade_size = get_trade_size(balance, allocation, vol)

    if acct_id not in TRADE_STATE:
        TRADE_STATE[acct_id] = {}

    # Entry rules: fast/slow VWAP crossover + RSI filter
    if fast_vwap > slow_vwap and rsi < 70 and symbol not in TRADE_STATE[acct_id]:
        resp = await place_order(acct_id, "buy", symbol, trade_size)
        if resp:
            entry_price = prices[-1]
            TRADE_STATE[acct_id][symbol] = {"side": "buy", "entry": entry_price, "size": trade_size, "ttp": entry_price * 1.01, "tsl": entry_price * 0.98}
            logger.info(f"[{acct_id}] BUY {symbol} @ {entry_price} size {trade_size}")

    elif fast_vwap < slow_vwap and rsi > 30 and symbol not in TRADE_STATE[acct_id]:
        resp = await place_order(acct_id, "sell", symbol, trade_size)
        if resp:
            entry_price = prices[-1]
            TRADE_STATE[acct_id][symbol] = {"side": "sell", "entry": entry_price, "size": trade_size, "ttp": entry_price * 0.99, "tsl": entry_price * 1.02}
            logger.info(f"[{acct_id}] SELL {symbol} @ {entry_price} size {trade_size}")

    await check_trailing(acct_id, symbol, prices)

    # dynamic per-symbol sleep to reduce rate limit risk
    await asyncio.sleep( max(1.0, min(15.0, (vol * 60) if vol and not pd.isna(vol) else 5.0)) )

# ---------- Per-account loop & main ----------
async def account_loop(account):
    while True:
        try:
            tasks = [trade_account_symbol(account, s) for s in SYMBOLS]
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.exception(f"Error in account loop: {e}")
        await asyncio.sleep(0.5)  # small pause between cycles

async def main():
    while True:
        accounts = await list_accounts()
        if not accounts:
            logger.warning("No accounts found; check COINBASE_ISS and PEM. Retrying in 20s...")
            await asyncio.sleep(20)
            continue

        # spawn one loop per account
        account_tasks = []
        for acct in accounts:
            account_tasks.append(account_loop(acct))
        await asyncio.gather(*account_tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
