import time
import logging

from strategy import MyStrategy
from executor_real import RealOrderExecutor
from safety import SafetyModule
from data_provider import DataProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def main():
    strategy = MyStrategy()  # instantiate your own strategy
    executor = RealOrderExecutor()  # real (not stub) order executor for Coinbase
    safety = SafetyModule()  # handles risk and halt triggers
    data = DataProvider()  # gets the latest candles

    logging.info("NIJA bot live loop started (real strategy -> executor wireup).")

    while True:
        try:
            candles = data.fetch_latest_candles()
            if not candles:
                logging.warning("No candle data, skipping cycle.")
                time.sleep(15)
                continue

            # Safety Checks (halt if needed)
            if safety.should_halt():
                logging.warning("Halted by safety module, skipping trading cycle.")
                time.sleep(120)
                continue

            # Get signal from your trading strategy (e.g. 'buy', 'sell', 'hold')
            signal = strategy.signal_at_index(candles, index=-1)
            logging.info(f"Signal: {signal}")

            # Wire-up: Only execute if a real trade should occur!
            if signal in ['buy', 'sell']:
                result = executor.submit_order(signal, candles[-1])
                logging.info(f"Order executed: {result}")
            else:
                logging.info("No actionable signal.")

        except Exception as e:
            logging.exception(f"Exception in trading loop: {e}")

        # Adjust this interval to match your candle granularity (e.g., 60 for 1m)
        time.sleep(60)

if __name__ == "__main__":
    main()
