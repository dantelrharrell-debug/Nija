import threading
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def start_bot():
    def run():
        logging.info("=== NIJA BOT STARTED ===")
        while True:
            # Replace this with your actual trading logic
            logging.info("NIJA bot running...")
            time.sleep(10)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
