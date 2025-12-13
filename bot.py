#!/usr/bin/env python3
"""
NIJA Trading Bot - Main Entry Point
Runs the complete APEX v7.1 strategy with Coinbase Advanced Trade API
"""

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler

# Setup paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'nija.log'))
logger = logging.getLogger("nija")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

if not logger.hasHandlers():
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

from trading_strategy import TradingStrategy


def main():
    """Main entry point for NIJA trading bot"""
    logger.info("=" * 70)
    logger.info("NIJA TRADING BOT - APEX v7.1")
    logger.info("Branch: %s", os.getenv("GIT_BRANCH", "unknown"))
    logger.info("Commit: %s", os.getenv("GIT_COMMIT", "unknown"))
    logger.info("=" * 70)
    logger.info(f"Python version: {sys.version.split()[0]}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Working directory: {os.getcwd()}")
    
    try:
        # Initialize trading strategy
        logger.info("Initializing trading strategy...")
        strategy = TradingStrategy()
        
        # Trading loop
        logger.info("Starting main trading loop...")
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                logger.info(f"Cycle #{cycle_count}")
                
                # Run one complete trading cycle
                strategy.run_trading_cycle()
                
                # Sleep before next cycle (2.5 minutes as specified)
                sleep_time = 150  # 2.5 minutes
                logger.info(f"Sleeping for {sleep_time} seconds until next cycle...")
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("Trading bot stopped by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}", exc_info=True)
                logger.info("Waiting 10 seconds before retry...")
                time.sleep(10)
    
    except Exception as e:
        logger.error(f"Fatal error initializing bot: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("NIJA trading bot shutdown complete")


if __name__ == "__main__":
    main()

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
