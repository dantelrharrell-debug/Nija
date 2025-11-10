# start_bot.py (top)
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

# import from repo-root shim so 'app' package problems can't crash startup
from nija_client import CoinbaseClient

import os
import sys

# Add current directory to path (root)
sys.path.append(os.path.dirname(__file__))

from nija_client import CoinbaseClient

def main():
    client = CoinbaseClient(advanced=True, debug=True)
    accounts = client.fetch_advanced_accounts()
    print("Fetched accounts:", accounts)

if __name__ == "__main__":
    main()
