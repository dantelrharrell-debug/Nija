import time
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

# Attempt to import your local modules first (keeps compatibility with your project structure).
# If not present, fall back to the packaged NIJA modules we prepared earlier.
try:
    from nija_strategy import NijaStrategy as UserNijaStrategy  # your original name
except Exception:
    UserNijaStrategy = None

try:
    from exchanges.coinbase import CoinbaseExecutor as UserCoinbaseExecutor
except Exception:
    UserCoinbaseExecutor = None

try:
    from exchanges.binance import BinanceExecutor as UserBinanceExecutor
except Exception:
    UserBinanceExecutor = None

try:
    from exchanges.kucoin import KuCoinExecutor as UserKuCoinExecutor
except Exception:
    UserKuCoinExecutor = None

try:
    from safety import SafetyModule as UserSafetyModule
except Exception:
    UserSafetyModule = None

try:
    from data_provider import DataProvider as UserDataProvider
except Exception:
    UserDataProvider = None

# Fallback to our packaged implementations if user modules aren't available
try:
    from nija_bot.strategy import NijaStrategy as PackagedNijaStrategy
except Exception:
    PackagedNijaStrategy = None

try:
    from nija_bot import executor_real as executor_real
except Exception:
    executor_real = None

# Market data fallback (ccxt)
try:
    import ccxt
except Exception:
    ccxt = None

# HTTP helper fallback
import requests

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
LOG = logging.getLogger("nija.bot")

# Config — tune with env vars if you like
SYMBOLS_TO_RUN = [
    ("BTC-USD", "coinbase"),
    ("ETH-USDT", "binance"),
    ("SOL-USDT", "kucoin"),
]
CANDLE_LIMIT = int(__import__("os").environ.get("NIJA_CANDLES", "300"))
TIMEFRAME = __import__("os").environ.get("NIJA_TIMEFRAME", "1m")
TRADE_JOURNAL_PATH = Path(__import__("os").environ.get("NIJA_TRADE_JOURNAL", "/usr/src/app/trade_journal.jsonl"))
ACCOUNT_BALANCE = float(__import__("os").environ.get("NIJA_ACCOUNT_BALANCE", "50000"))
SLEEP_SECONDS = int(__import__("os").environ.get("NIJA_LOOP_SLEEP", "60"))  # match candle timeframe


# -------------------- Helpers & Fallbacks --------------------
def make_strategy():
    if UserNijaStrategy is not None:
        return UserNijaStrategy()
    if PackagedNijaStrategy is not None:
        return PackagedNijaStrategy()
    raise RuntimeError("No NijaStrategy implementation found. Add `nija_strategy` or install packaged module.")

def make_executor_by_name(name: str, account_balance: float = ACCOUNT_BALANCE):
    name = name.lower()
    # prefer user-provided executors if available
    if name == "coinbase" and UserCoinbaseExecutor is not None:
        return UserCoinbaseExecutor()
    if name == "binance" and UserBinanceExecutor is not None:
        return UserBinanceExecutor()
    if name == "kucoin" and UserKuCoinExecutor is not None:
        return UserKuCoinExecutor()

    # fallback to packaged executor_real
    if executor_real is not None:
        # map kucoin -> binance fallback if user doesn't have kucoin executor
        if name == "kucoin":
            # prefer a dedicated KuCoin if present; otherwise use binance executor
            if UserKuCoinExecutor is not None:
                return UserKuCoinExecutor()
            name = "binance"

        try:
            return executor_real.make_executor(name, account_balance=account_balance)
        except Exception:
            LOG.warning("executor_real.make_executor failed for %s; defaulting to simulation executor", name)
    # simulation fallback: minimal stub executor using executor_real.ExchangeExecutor if available
    class StubExecutor:
        def __init__(self):
            self.account_balance = account_balance
            self.max_position_pct = 0.10
            self.halted = False
            self.logger = LOG
        def get_market_price(self, symbol):
            return 100.0
        def submit_market_order(self, symbol, side, qty, **kwargs):
            oid = f"sim-{int(time.time()*1000)}"
            return {'id': oid, 'status': 'filled', 'filled_qty': qty, 'avg_price': self.get_market_price(symbol)}
        def submit_limit_order(self, *args, **kwargs):
            return self.submit_market_order(*args, **kwargs)
        def cancel_order(self, *args, **kwargs):
            return True
        def check_risk_limits(self, *args, **kwargs):
            return True
    LOG.warning("Using StubExecutor for %s", name)
    return StubExecutor()


def make_data_provider():
    if UserDataProvider is not None:
        try:
            return UserDataProvider()
        except Exception as e:
            LOG.exception("User DataProvider failed to init: %s", e)
    # fallback simple provider using ccxt if available, otherwise Coinbase public candles
    class FallbackDataProvider:
        def __init__(self):
            # pick a ccxt client if available for public fetches
            self.ccxt_clients = {}
            if ccxt is not None:
                # instantiate a public exchange client for binance (others could be added)
                try:
                    self.ccxt_clients['binance'] = ccxt.binance()
                except Exception:
                    self.ccxt_clients = {}

        def fetch_latest_candles(self, symbol, exchange, limit=CANDLE_LIMIT, timeframe=TIMEFRAME):
            # try ccxt client if available
            if exchange.lower() in ("binance", "kucoin") and 'binance' in self.ccxt_clients:
                client = self.ccxt_clients['binance']
                try:
                    # ccxt expects 'ETH/USDT' style
                    ccxt_symbol = symbol.replace("-", "/")
                    ohlcv = client.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, limit=limit)
                    df = _ohlcv_to_df(ohlcv)
                    return df
                except Exception as e:
                    LOG.debug("ccxt fetch failed for %s@%s: %s", symbol, exchange, e)

            # fallback: Coinbase public candles for product-id style (BTC-USD)
            if exchange.lower().startswith("coin"):
                try:
                    product_id = symbol.replace("/", "-").upper()
                    gran = 60 if timeframe == "1m" else 300
                    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles"
                    r = requests.get(url, params={"granularity": gran, "limit": limit}, timeout=10)
                    r.raise_for_status()
                    raw = r.json()
                    # raw rows: [time, low, high, open, close, volume]
                    df = _coinbase_raw_to_df(raw)
                    return df
                except Exception as e:
                    LOG.debug("Coinbase public candles failed: %s", e)
            # ultimate fallback: return None
            return None

    def _ohlcv_to_df(ohlcv):
        import pandas as pd
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        return df.sort_index()

    def _coinbase_raw_to_df(raw):
        import pandas as pd
        # Coinbase returns list in descending time order [time, low, high, open, close, volume]
        df = pd.DataFrame(raw, columns=["time", "low", "high", "open", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].set_index("timestamp")
        return df.sort_index()

    return FallbackDataProvider()


def write_trade_journal(entry: dict):
    try:
        TRADE_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRADE_JOURNAL_PATH, "a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        LOG.exception("Failed to write trade journal entry")


# ----------------- Main -----------------
def main():
    LOG.info("\u1F680 Starting NIJA trading bot (integrated runner)")

    strategy = make_strategy()
    data = make_data_provider()
    safety = UserSafetyModule() if UserSafetyModule is not None else None

    # build executor instances per exchange
    executors = {}
    for _, exch in SYMBOLS_TO_RUN:
        if exch not in executors:
            executors[exch] = make_executor_by_name(exch, account_balance=ACCOUNT_BALANCE)

    LOG.info("Executors ready: %s", ", ".join(executors.keys()))

    # main loop
    while True:
        try:
            LOG.info("Running trading cycle: %s UTC", datetime.now(timezone.utc).isoformat())

            for symbol, exchange in SYMBOLS_TO_RUN:
                try:
                    LOG.debug("Cycle for %s @ %s", symbol, exchange)
                    df = data.fetch_latest_candles(symbol, exchange, limit=CANDLE_LIMIT, timeframe=TIMEFRAME)
                    if df is None or len(df) < 80:
                        LOG.warning("[%s %s] Not enough candles (%s). Skipping.", exchange, symbol, None if df is None else len(df))
                        continue

                    # convert to pandas DataFrame with expected columns if provider gave a list/dict
                    import pandas as pd
                    if not isinstance(df, pd.DataFrame):
                        # assume list of dicts
                        df = pd.DataFrame(df)

                    # calculate indicators
                    ind = strategy.calculate_indicators(df)

                    last_idx = len(ind) - 1
                    last_row = ind.iloc[last_idx]
                    LOG.info("[%s %s] close=%.6f ema9=%.6f ema21=%.6f vwap=%.6f macd_hist=%.6f adx=%.2f rsi=%.2f",
                             exchange, symbol, last_row['close'], last_row['ema9'], last_row['ema21'], last_row['vwap'],
                             last_row['macd_hist'], last_row['adx'], last_row['rsi'])

                    # Safety: user safety module (if present)
                    if safety is not None:
                        try:
                            if safety.should_halt(symbol, exchange):
                                LOG.warning("[%s %s] Halted by SafetyModule. Skipping.", exchange, symbol)
                                continue
                        except Exception:
                            LOG.exception("SafetyModule check failed; continuing without halting.")

                    # generate signal using strategy API compatible with earlier implementation
                    # Supports: user strategy that returns (signal, indicators) OR packaged strategy with signal_at_index
                    sig_obj = None
                    try:
                        # prefer new combined API if user provided it
                        if hasattr(strategy, "generate_signal_and_indicators"):
                            signal, indicators = strategy.generate_signal_and_indicators(df)
                            LOG.debug("[%s %s] strategy.generate_signal_and_indicators -> %s", exchange, symbol, signal)
                            # If signal is structured, we expect 'buy'/'sell'/'none' or similar
                            if signal in ("buy", "sell"):
                                # Build a simple signal object with entry and stop approximations
                                # If user strategy supplies 'entry' and 'stop' include them; otherwise estimate stop using ATR
                                entry_price = last_row['close']
                                stop = indicators.get('stop') if isinstance(indicators, dict) and indicators.get('stop') else (entry_price - last_row['atr14']*1.0 if signal=="buy" else entry_price + last_row['atr14']*1.0)
                                from types import SimpleNamespace
                                sig_obj = SimpleNamespace(side=("long" if signal=="buy" else "short"), entry=entry_price, stop=stop, tp1=None, tp2=None, tp3=None, rr=None)
                        else:
                            # packaged strategy path: use signal_at_index
                            ts = strategy.signal_at_index(ind, last_idx)
                            if ts is not None:
                                sig_obj = ts
                    except Exception as e:
                        LOG.exception("Strategy signal generation failed: %s", e)

                    if sig_obj is None:
                        LOG.info("[%s %s] No actionable signal.", exchange, symbol)
                        continue

                    # log the full structured signal
                    LOG.info("[%s %s] SIGNAL: side=%s entry=%.6f stop=%.6f", exchange, symbol, sig_obj.side, sig_obj.entry, sig_obj.stop)

                    # Select executor
                    executor = executors.get(exchange)
                    if executor is None:
                        LOG.error("[%s %s] No executor configured for exchange %s", exchange, symbol, exchange)
                        continue

                    # Check safety at executor (halted, daily limit, etc)
                    if getattr(executor, "halted", False):
                        LOG.warning("[%s %s] Executor halted by safety module. Skipping.", exchange, symbol)
                        continue

                    # Compute position size
                    stop_distance = abs(sig_obj.entry - sig_obj.stop)
                    # Get recommended risk percent if available from strategy
                    risk_pct = 0.05  # default 5%
                    try:
                        if hasattr(strategy, "recommend_risk_pct"):
                            risk_pct = strategy.recommend_risk_pct(float(last_row['adx']))
                    except Exception:
                        LOG.debug("Could not compute recommend_risk_pct; using default 5%")

                    # dollars risk
                    dollars_risk = executor.account_balance * risk_pct
                    qty = 0
                    if stop_distance > 0:
                        qty = int(max(1, dollars_risk / stop_distance))
                    else:
                        LOG.warning("[%s %s] stop_distance not positive; set qty=0", exchange, symbol)

                    if qty <= 0:
                        LOG.warning("[%s %s] Computed qty <= 0 (dollars_risk=%.2f stop_distance=%.6f). Skipping.", exchange, symbol, dollars_risk, stop_distance)
                        continue

                    # final risk limit check via executor
                    current_price = executor.get_market_price(symbol.replace("-", "/") if "/" in symbol else symbol.replace("/", "-"))
                    if not getattr(executor, "check_risk_limits", lambda a,b,c: True)(symbol, qty, current_price):
                        LOG.warning("[%s %s] Executor rejected risk limits for qty=%s price=%.6f", exchange, symbol, qty, current_price)
                        continue

                    # Place market order (simulated if in simulation)
                    side = "buy" if sig_obj.side in ("long","buy") else "sell"
                    LOG.info("[%s %s] Placing market order: side=%s qty=%s approx_price=%.6f", exchange, symbol, side, qty, current_price)
                    try:
                        order = executor.submit_market_order(symbol.replace("/", "-") if exchange.lower().startswith("coin") else symbol.replace("-", "/"), side, qty)
                        LOG.info("[%s %s] Order result: %s", exchange, symbol, order)
                        # Record trade journal
                        write_trade_journal({
                            "time": datetime.now(timezone.utc).isoformat(),
                            "exchange": exchange,
                            "symbol": symbol,
                            "signal": {"side": sig_obj.side, "entry": sig_obj.entry, "stop": sig_obj.stop},
                            "qty": qty,
                            "order": order
                        })
                        # If executor supports record_trade_result, let it know PnL after trade later (the backtester or live monitor should compute PnL)
                    except Exception as e:
                        LOG.exception("[%s %s] Order placement failed: %s", exchange, symbol, e)

                except Exception as inner_e:
                    LOG.exception("Inner loop error for %s@%s: %s", symbol, exchange, inner_e)

        except Exception as e:
            LOG.exception("Top-level loop exception: %s", e)

        LOG.info("Sleeping %s seconds before next cycle.", SLEEP_SECONDS)
        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()
