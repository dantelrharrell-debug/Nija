import time
import logging
import traceback

# Setup logging
logging.basicConfig(
    filename="nija_bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Import your trading logic
try:
    from coinbase_advanced_py.client import CoinbaseClient
except ImportError:
    CoinbaseClient = None
    logging.warning("⚠️ coinbase_advanced_py.client not found. Real trading disabled.")

# Global flag for running
running = True

def start_trading(client=None):
    logging.info("🚀 Starting Nija trading loop")
    
    while running:
        try:
            # Example: replace with your live trade function
            if client:
                # Put your trade execution logic here
                logging.info("🔹 Checking market and executing trades...")
            else:
                logging.info("🔹 Simulation mode: client not initialized")

            # Sleep between iterations
            time.sleep(5)  # adjust for frequency of checks

        except KeyboardInterrupt:
            logging.info("⏹ KeyboardInterrupt detected, shutting down")
            break
        except Exception as e:
            logging.error(f"❌ Error in trading loop: {e}")
            logging.error(traceback.format_exc())
            logging.info("🔁 Waiting 10 seconds before retry")
            time.sleep(10)  # avoid crash loops

    logging.info("🛑 Nija bot stopped")

# Optional safe exit function
def stop_trading():
    global running
    running = False
