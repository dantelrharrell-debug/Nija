import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from trading_strategy import TradingStrategy

# Main trading logic and bot initialization goes here...
def run_live_trading():
    # ── Production pre-flight (Redis PING, lock logging, single-instance,
    #    stale-lock clearance, live-mode verification) ─────────────────────
    try:
        from bot.production_preflight import run_preflight
        run_preflight()
    except SystemExit:
        raise  # propagate clean exit from pre-flight failures
    except Exception as _pf_exc:
        logging.getLogger("nija").critical(
            "Pre-flight check raised unexpectedly: %s", _pf_exc, exc_info=True
        )
        sys.exit(1)

    # Setup logging
    LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'nija.log'))
    logger = logging.getLogger("nija")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    if not logger.hasHandlers():
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    logger.info("Initializing trading bot...")
    try:
        strategy = TradingStrategy()
    except Exception as e:
        logger.error(f"Fatal error during bot initialisation: {e}", exc_info=True)
        sys.exit(1)

    # Post-connection delay: allow nonce state to stabilise before the first
    # market scan.  The TradingStrategy __init__ already waits 45 s *before*
    # connecting; this additional pause runs *after* all brokers are connected
    # so the first run_trading_cycle() does not race against freshly-issued
    # nonces and trigger nonce-thrashing errors.
    _post_connect_delay = int(os.getenv("NIJA_POST_CONNECT_DELAY", "7"))
    if _post_connect_delay > 0:
        logger.info(
            f"⏱️  Post-connection stabilisation delay: {_post_connect_delay}s "
            "(override with NIJA_POST_CONNECT_DELAY env var)"
        )
        time.sleep(_post_connect_delay)
        logger.info("✅ Post-connection delay complete — starting first scan cycle")

    _cycle_error_count = 0
    _MAX_CONSECUTIVE_ERRORS = int(os.getenv("NIJA_MAX_CYCLE_ERRORS", "10"))
    while True:
        try:
            start = time.perf_counter()
            strategy.run_cycle()
            duration = time.perf_counter() - start
            logger.info(f"Scan cycle: {duration:.4f}s")
            _cycle_error_count = 0  # reset on success
        except Exception as e:
            _cycle_error_count += 1
            logger.error(
                f"Scan cycle error ({_cycle_error_count}/{_MAX_CONSECUTIVE_ERRORS}): {e}",
                exc_info=True,
            )
            if _cycle_error_count >= _MAX_CONSECUTIVE_ERRORS:
                logger.critical(
                    "Too many consecutive scan cycle errors — restarting process"
                )
                sys.exit(1)
            time.sleep(30)  # brief back-off before retrying
            continue
        time.sleep(150)

if __name__ == "__main__":
    run_live_trading()
