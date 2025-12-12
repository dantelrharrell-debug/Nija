#!/usr/bin/env python3
"""
NIJA Master Runner - bot.py
Drop this into /usr/src/app/bot.py and restart container.

Expect the following package layout (we used earlier):
- nija_bot.strategy OR strategies.master_strategy (master strategy)
- nija_bot.executor_real OR executor_real (multi-exchange executors)
- indicators.ta_engine (TAEngine)
- risk.position_sizer (PositionSizer)
- risk.stop_engine (StopEngine)
"""

import os
import time
import json
import logging
import traceback
from datetime import datetime, timezone

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija.bot")

# Coinbase RESTClient - use the correct constructor (no api_url)
try:
    from coinbase.rest import RESTClient as CoinbaseRESTClient
except Exception:
    CoinbaseRESTClient = None
    LOG.info("coinbase.rest.RESTClient not available; Coinbase executor will run in simulation mode.")

# Try import packaged modules (created earlier). Fallbacks are provided.
try:
    from strategies.master_strategy import NijaMasterStrategy
except Exception:
    NijaMasterStrategy = None

try:
    import executor_real
except Exception:
    executor_real = None

try:
    from indicators.ta_engine import TAEngine
except Exception:
    TAEngine = None

try:
    from risk.position_sizer import PositionSizer
    from risk.stop_engine import StopEngine
except Exception:
    PositionSizer = None
    StopEngine = None

# Settings (env-driven)
SYMBOLS = os.getenv("NIJA_SYMBOLS", "BTC-USD:coinbase,ETH-USDT:binance,SOL-USDT:binance")
# Format: "SYMBOL:exchange,SYMBOL:exchange"
SYMBOLS = [tuple(s.split(":")) for s in SYMBOLS.split(",") if ":" in s]
TIMEFRAME = os.getenv("NIJA_TIMEFRAME", "1m")
CANDLE_LIMIT = int(os.getenv("NIJA_CANDLES", "300"))
SLEEP_SECONDS = int(os.getenv("NIJA_LOOP_SLEEP", "60"))
TRADE_JOURNAL = os.getenv("NIJA_TRADE_JOURNAL", "/usr/src/app/trade_journal.jsonl")
ACCOUNT_BALANCE = float(os.getenv("NIJA_ACCOUNT_BALANCE", "50000"))

# Safety defaults
MAX_CONSECUTIVE_LOSSES = int(os.getenv("NIJA_MAX_CONSECUTIVE_LOSSES", "3"))
DAILY_LOSS_PCT = float(os.getenv("NIJA_DAILY_LOSS_PCT", "0.04"))
MIN_CANDLES_REQUIRED = int(os.getenv("NIJA_MIN_CANDLES_REQUIRED", "80"))
MIN_TIME_BETWEEN_TRADES = float(os.getenv("NIJA_MIN_TIME_BETWEEN_TRADES", "5"))  # seconds

# Make strategy
def make_strategy():
    if NijaMasterStrategy is not None:
        return NijaMasterStrategy()
    # fallback simple packaged master if present at nija_bot.strategy
    try:
        from nija_bot.strategy import NijaStrategy as FallbackStrat
        return FallbackStrat()
    except Exception:
        LOG.error("No strategy implementation found. Exiting.")
        raise

# Make executor factory
def make_executor(name: str, balance: float = ACCOUNT_BALANCE):
    # Prefer executor_real factory if available
    if executor_real is not None and hasattr(executor_real, "make_executor"):
        try:
            return executor_real.make_executor(name, account_balance=balance)
        except Exception as e:
            LOG.exception("executor_real.make_executor failed for %s: %s", name, e)

    # final fallback stub
    class StubExec:
        def __init__(self):
            self.account_balance = balance
            self.max_position_pct = 0.10
            self.halted = False
        def get_market_price(self, symbol):
            return 100.0
        def submit_market_order(self, symbol, side, qty, **kwargs):
            oid = f"sim-{int(time.time()*1000)}"
            LOG.info("[SIM] %s %s qty=%s price~%.2f", side.upper(), symbol, qty, self.get_market_price(symbol))
            return {"id":oid, "status":"filled", "filled_qty":qty, "avg_price":self.get_market_price(symbol)}
        def check_risk_limits(self, symbol, qty, price):
            return True
        def cancel_order(self, oid): return True
    LOG.warning("Using StubExecutor for exchange %s", name)
    return StubExec()

# Make data provider fallback (TAEngine.load if no DataProvider)
def fetch_latest_candles(symbol, exchange, limit=CANDLE_LIMIT, timeframe=TIMEFRAME):
    """
    Prefer a data provider module if present, otherwise use TAEngine.load as fallback (which may use synthetic data).
    """
    # If a user DataProvider exists, try to use it
    try:
        from data_provider import DataProvider
        dp = DataProvider()
        df = dp.fetch_latest_candles(symbol, exchange, limit=limit, timeframe=timeframe)
        return df
    except Exception:
        pass

    # Try TAEngine fallback
    if TAEngine is not None:
        ta = TAEngine()
        df = ta.load(symbol)  # will generate synthetic data if no candles passed
        return df

    LOG.error("No data provider or TAEngine available to fetch candles.")
    return None

# Utilities
def write_trade_journal(entry: dict):
    try:
        os.makedirs(os.path.dirname(TRADE_JOURNAL), exist_ok=True)
        with open(TRADE_JOURNAL, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        LOG.exception("Failed to write trade journal")

# Simple performance tracker for safety
class PerfTracker:
    def __init__(self, balance=ACCOUNT_BALANCE):
        self.recent_results = []
        self.balance = balance

    def record(self, pnl):
        self.recent_results.append(float(pnl))
        if len(self.recent_results) > 50:
            self.recent_results = self.recent_results[-50:]

    def consecutive_losses(self):
        cnt = 0
        for p in reversed(self.recent_results):
            if p < 0: cnt += 1
            else: break
        return cnt

    def daily_loss(self):
        total_loss = sum([p for p in self.recent_results if p < 0])
        return abs(total_loss)

perf = PerfTracker()

# Instantiate core components
strategy = make_strategy()
executors = {}
for _, exch in SYMBOLS:
    if exch not in executors:
        executors[exch] = make_executor(exch, balance=ACCOUNT_BALANCE)
LOG.info("Executors available: %s", ", ".join(executors.keys()))

sizer = PositionSizer() if PositionSizer is not None else None
stop_engine = StopEngine() if StopEngine is not None else None

# Optional: init Coinbase RESTClient with only supported args (no api_url)
coinbase_client = None
if CoinbaseRESTClient is not None:
    try:
        coinbase_client = CoinbaseRESTClient(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET")
        )
        LOG.info("Coinbase RESTClient initialized")
    except Exception:
        LOG.exception("Coinbase RESTClient init error - continuing with executors (may simulate)")

# Helper: compute qty (dollars risk / stop_distance)
def compute_qty(executor, entry_price, stop_price, adx_value=None):
    # ask strategy for recommended risk if available
    risk_pct = 0.05
    try:
        if hasattr(strategy, "recommend_risk_pct"):
            risk_pct = strategy.recommend_risk_pct(adx_value if adx_value is not None else 0.0)
    except Exception:
        pass
    # enforce min/max (2% - 10%)
    risk_pct = max(0.02, min(0.10, risk_pct))
    dollars_risk = executor.account_balance * risk_pct
    stop_dist = abs(entry_price - stop_price)
    if stop_dist <= 1e-8:
        return 0
    qty = int(dollars_risk / stop_dist)
    return max(0, qty)

# Main trading loop
_last_trade_ts = 0
def main_loop():
    global _last_trade_ts
    LOG.info("NIJA main loop starting — symbols: %s", [s for s,_ in SYMBOLS])

    while True:
        try:
            now = datetime.now(timezone.utc)
            LOG.info("Running trading cycle at %s", now.isoformat())

            for symbol, exchange in SYMBOLS:
                try:
                    df = fetch_latest_candles(symbol, exchange, limit=CANDLE_LIMIT, timeframe=TIMEFRAME)
                    if df is None:
                        LOG.warning("[%s %s] No candles returned. Skipping.", exchange, symbol)
                        continue
                    # Check data length
                    try:
                        import pandas as pd
                        if not isinstance(df, pd.DataFrame):
                            df = pd.DataFrame(df)
                    except Exception:
                        pass

                    if len(df) < MIN_CANDLES_REQUIRED:
                        LOG.warning("[%s %s] Not enough candles (%d). Need %d. Skipping.", exchange, symbol, len(df), MIN_CANDLES_REQUIRED)
                        continue

                    # Compute indicators via strategy/TAEngine
                    # Master strategy accepts optional candles_df param (our scaffolding)
                    try:
                        sig = None
                        if hasattr(strategy, "get_signal"):
                            sig = strategy.get_signal(symbol, candles_df=df)
                        elif hasattr(strategy, "signal_at_index"):
                            ind = strategy.calculate_indicators(df)
                            sig_obj = strategy.signal_at_index(ind, len(ind)-1)
                            sig = None if sig_obj is None else ("BUY" if getattr(sig_obj, "side", "") in ("long","buy") else "SELL")
                        else:
                            LOG.error("Strategy has no compatible signal api")
                            continue
                    except Exception:
                        LOG.exception("Strategy.get_signal failed for %s@%s", symbol, exchange)
                        continue

                    LOG.info("[%s %s] Signal: %s", exchange, symbol, str(sig))

                    if sig not in ("BUY", "SELL"):
                        continue

                    # pick executor for exchange
                    executor = executors.get(exchange)
                    if executor is None:
                        LOG.warning("[%s %s] No executor configured. Skipping.", exchange, symbol)
                        continue
                    if getattr(executor, "halted", False):
                        LOG.warning("[%s %s] Executor halted by safety module. Skipping.", exchange, symbol)
                        continue

                    # Estimate entry and stop using latest row & ATR fallback
                    last_row = df.iloc[-1]
                    entry_price = float(last_row.get("close", last_row.get("last", last_row)))
                    # default stop: 1 ATR behind
                    atr = float(last_row.get("atr14", last_row.get("atr", 0.0) or 0.0))
                    if sig == "BUY":
                        stop_price = entry_price - max(1e-6, atr * 1.0)
                    else:
                        stop_price = entry_price + max(1e-6, atr * 1.0)

                    # compute qty
                    adx_val = float(last_row.get("adx", 0.0))
                    qty = compute_qty(executor, entry_price, stop_price, adx_value=adx_val)
                    if qty <= 0:
                        LOG.warning("[%s %s] qty computed 0. Skipping.", exchange, symbol)
                        continue

                    # rate-limit check
                    if time.time() - _last_trade_ts < MIN_TIME_BETWEEN_TRADES:
                        LOG.warning("Global rate limit preventing new trade (last trade %.1fs ago).", time.time() - _last_trade_ts)
                        continue

                    # final executor risk check
                    try:
                        price_for_check = executor.get_market_price(symbol.replace("-", "/") if "/" in symbol else symbol)
                    except Exception:
                        price_for_check = entry_price

                    if hasattr(executor, "check_risk_limits") and not executor.check_risk_limits(symbol, qty, price_for_check):
                        LOG.warning("[%s %s] Executor risk check rejected order qty=%s price=%.6f", exchange, symbol, qty, price_for_check)
                        continue

                    # Place market order
                    side = "buy" if sig == "BUY" else "sell"
                    LOG.info("[%s %s] Placing market order: side=%s qty=%s entry~%.6f stop~%.6f", exchange, symbol, side, qty, entry_price, stop_price)
                    order = executor.submit_market_order(symbol.replace("-", "/") if not symbol.endswith("-USD") else symbol, side, qty)
                    LOG.info("[%s %s] Order result: %s", exchange, symbol, str(order))

                    # Register stop in StopEngine if available
                    if stop_engine is not None:
                        stop_engine.set_initial_stop(symbol, stop_price)

                    # Write trade journal entry
                    write_trade_journal({
                        "time": datetime.now(timezone.utc).isoformat(),
                        "exchange": exchange,
                        "symbol": symbol,
                        "signal": sig,
                        "entry_price": entry_price,
                        "stop_price": stop_price,
                        "qty": qty,
                        "order": order
                    })

                    _last_trade_ts = time.time()

                except Exception:
                    LOG.exception("Inner symbol loop failure for %s@%s", symbol, exchange)

            # End of symbol loop — safety checks
            if perf.consecutive_losses() >= MAX_CONSECUTIVE_LOSSES:
                LOG.warning("Max consecutive losses reached (%d). Halting trading.", perf.consecutive_losses())
                # Halt all executors
                for e in executors.values():
                    setattr(e, "halted", True)

            # Daily loss cap
            if perf.daily_loss() > (DAILY_LOSS_PCT * ACCOUNT_BALANCE):
                LOG.warning("Daily loss cap exceeded. Halting trading and requiring manual review.")
                for e in executors.values():
                    setattr(e, "halted", True)

        except KeyboardInterrupt:
            LOG.info("NIJA bot stopped by user.")
            break
        except Exception:
            LOG.exception("Top-level loop exception")
            time.sleep(5)

        LOG.info("Sleeping %s seconds until next cycle.", SLEEP_SECONDS)
        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    LOG.info("Starting NIJA Master Runner")
    main_loop()
