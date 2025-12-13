import time
import logging
from datetime import datetime

from nija_strategy import NijaStrategy
from exchanges.coinbase import CoinbaseExecutor
from safety import SafetyModule
from data_provider import DataProvider

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ---------------- CONFIG ----------------
SYMBOLS = [
    ("BTC-USD", "coinbase"),
    ("ETH-USD", "coinbase"),
]

LOOP_INTERVAL = 60  # seconds (1m candles)

# ---------------- MAIN ----------------
def main():
    logging.info("🧠 Initializing NIJA Master Trading Engine")

    data = DataProvider()
    strategy = NijaStrategy()
    safety = SafetyModule()
    executor = CoinbaseExecutor()

    logging.info("🚀 NIJA bot LIVE — awaiting signals")

    while True:
        try:
            for symbol, exchange in SYMBOLS:
                logging.info(f"🔍 Scanning {exchange} {symbol}")

                candles = data.fetch_latest_candles(
                    symbol=symbol,
                    exchange=exchange,
                    limit=strategy.required_candles
                )

                if not candles or len(candles) < strategy.required_candles:
                    logging.warning(f"{symbol} | Not enough candle data")
                    continue

                if safety.should_halt(symbol, exchange):
                    logging.warning(f"{symbol} | HALTED by safety module")
                    continue

                signal, meta = strategy.generate_signal_and_indicators(candles)
                price = candles[-1]["close"]

                logging.info(
                    f"{symbol} | Price={price} | Signal={signal} | Meta={meta}"
                )

                if signal in ("buy", "sell"):
                    result = executor.submit_order(
                        symbol=symbol,
                        side=signal,
                        price=price,
                        meta=meta
                    )
                    logging.info(f"{symbol} | ORDER RESULT: {result}")
                else:
                    logging.info(f"{symbol} | No trade")

        except Exception as e:
            logging.exception(f"🔥 Fatal loop error: {e}")

        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    logging.info("⚔️ STARTING NIJA TRADING BOT ⚔️")
    main()
