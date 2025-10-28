import time
import logging
import traceback

# Logging setup
logging.basicConfig(
    filename="nija_bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

try:
    from coinbase_advanced_py.client import CoinbaseClient
except ImportError:
    CoinbaseClient = None
    logging.warning("⚠️ coinbase_advanced_py.client not found. Real trading disabled.")

running = True

def start_trading(client=None):
    logging.info("🚀 Starting Nija trading loop")

    while running:
        try:
            if client:
                # Replace with your trade logic
                logging.info("🔹 Checking market and executing trades...")
                # Example: client.get_accounts()
            else:
                logging.info("🔹 Simulation mode: client not initialized")

            time.sleep(5)

        except KeyboardInterrupt:
            logging.info("⏹ KeyboardInterrupt detected, stopping bot")
            break
        except Exception as e:
            logging.error(f"❌ Error in trading loop: {e}")
            logging.error(traceback.format_exc())
            logging.info("🔁 Retrying in 10 seconds")
            time.sleep(10)

    logging.info("🛑 Nija bot stopped")

def stop_trading():
    global running
    running = False
