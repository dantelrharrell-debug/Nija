import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def main():
    # Replace this with real Coinbase balance check
    accounts = ["BTC", "ETH"]  # mock example
    if not accounts:
        logging.error("❌ No funded accounts found. Exiting.")
        sys.exit(1)
    logging.info(f"✅ Funded accounts found: {accounts}")
    sys.exit(0)

if __name__ == "__main__":
    main()
